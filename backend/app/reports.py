"""
A lightweight, PeopleDesk-native report builder, and a scheduler that e-mails a saved report on a
cadence.

A report definition (`reportDefs`) names a base collection, a list of filters (field/operator/value)
and the columns to show. Filtering happens in Python over the already-loaded JSON records -- the
same whole-state-in-memory approach the rest of the app takes -- not pushed SQL, because company
datasets here are small and the records have no enforced schema to build SQL filters against safely.
REPORTABLE is a UI hint (what fields to suggest in the picker), not an allow-list: run() reads any
field name it is given straight off the record's JSON with dict.get(), known or not.

The scheduler (tick()/start()) mirrors reimb.py's own background-thread pattern exactly: a daemon
thread, a short sleep, then a poll every REPORT_TICK_MIN minutes (default 60) for any reportSchedules
record that is due, which runs its report, builds the Excel file, and e-mails it as an attachment
through an e-mail template (see email_templates.py, mail key "report.scheduled").
"""
import io
import logging
import os
import threading
import time
from datetime import datetime

from openpyxl import Workbook
from openpyxl.utils import get_column_letter
from sqlalchemy import text

from . import email_templates, mailer, repo

log = logging.getLogger("peopledesk")

# collection name -> {label, fields: [(field, label), ...]} -- a picker hint, not an allow-list
REPORTABLE = {
    "employees": {"label": "Employees", "fields": [("empNo", "Employee no."), ("firstName", "First name"), ("lastName", "Last name"),
                  ("email", "E-mail"), ("role", "Role"), ("status", "Status"), ("deptId", "Department"), ("managerId", "Manager"), ("doj", "Date of joining")]},
    "leaveReqs": {"label": "Leave requests", "fields": [("empId", "Employee"), ("status", "Status"), ("from", "From date"), ("to", "To date"), ("days", "Days")]},
    "expenseClaims": {"label": "Expense claims", "fields": [("empId", "Employee"), ("no", "Claim no."), ("status", "Status"), ("total", "Total")]},
    "punches": {"label": "Attendance", "fields": [("empId", "Employee"), ("date", "Date"), ("in", "Punch in"), ("out", "Punch out")]},
    "exits": {"label": "Exits", "fields": [("empId", "Employee"), ("status", "Status"), ("lwd", "Last working day"), ("reason", "Reason")]},
    "onboardings": {"label": "Onboarding", "fields": [("empId", "Employee"), ("status", "Status"), ("doj", "Date of joining")]},
    "assets": {"label": "Assets", "fields": [("type", "Type"), ("tag", "Tag"), ("status", "Status"), ("empId", "Held by")]},
    "trainings": {"label": "Trainings", "fields": [("title", "Title"), ("status", "Status"), ("start", "Start date")]},
}

OPS = ("equals", "notEquals", "contains", "before", "after", "in")


def catalogue() -> list[dict]:
    return [{"collection": k, "label": v["label"], "fields": v["fields"]} for k, v in REPORTABLE.items()]


def _match(value, op: str, target) -> bool:
    if op == "equals":
        return str(value or "") == str(target or "")
    if op == "notEquals":
        return str(value or "") != str(target or "")
    if op == "contains":
        return str(target or "").lower() in str(value or "").lower()
    if op == "before":
        return str(value or "") != "" and str(value) < str(target or "")
    if op == "after":
        return str(value or "") != "" and str(value) > str(target or "")
    if op == "in":
        opts = [x.strip() for x in str(target or "").split(",") if x.strip()]
        return str(value or "") in opts
    return True


def _visible_company_ids(conn, ctx) -> set | None:
    """None means every company (the group administrator, with no private companies to exclude)."""
    if ctx.is_super and not ctx.private:
        return None
    all_ids = {r[0] for r in conn.execute(text("SELECT id FROM companies"))}
    return {c for c in all_ids if ctx.is_hr_for(c)}


def columns_for(report_def: dict) -> list[str]:
    allowed = [f for f, _ in REPORTABLE.get(report_def.get("baseCollection"), {}).get("fields", [])]
    return [c for c in (report_def.get("columns") or allowed) if c in allowed] or allowed


def _rows_for(conn, report_def: dict, visible: set | None) -> list[dict]:
    coll = report_def.get("baseCollection")
    # only what the catalogue offers: its collections and their fields (no salaries or bank details by asking)
    if coll not in REPORTABLE or coll not in repo.BY_NAME:
        raise ValueError(f"unknown collection: {coll}")
    allowed = [f for f, _ in REPORTABLE[coll]["fields"]]
    report_def = {**report_def, "columns": [c for c in (report_def.get("columns") or allowed) if c in allowed] or allowed,
                  "filters": [f for f in (report_def.get("filters") or []) if (f or {}).get("field") in allowed]}
    rows = [repo.loads(d) for d in conn.execute(text(f"SELECT data FROM {repo.BY_NAME[coll].table}")).scalars()]
    if visible is not None:
        # a row belongs to its companyId, or else to the company of the employee it is about (leave, punches…)
        emp_co = {r[0]: r[1] for r in conn.execute(text("SELECT id, company_id FROM employees"))}
        rows = [r for r in rows if (r.get("companyId") or emp_co.get(r.get("empId"))) in visible]
    for f in report_def.get("filters") or []:
        field, op, target = f.get("field"), f.get("op"), f.get("value")
        if field and op in OPS:
            rows = [r for r in rows if _match(r.get(field), op, target)]
    cols = report_def.get("columns") or [f for f, _ in REPORTABLE.get(coll, {}).get("fields", [])]
    return [{c: r.get(c) for c in cols} for r in rows]


def run(conn, report_def: dict, ctx) -> list[dict]:
    """The interactive path: scoped to whatever companies the acting person (ctx) may see."""
    return _rows_for(conn, report_def, _visible_company_ids(conn, ctx))


def run_unattended(conn, report_def: dict) -> list[dict]:
    """The scheduler's path: no acting person, so scoped to the company the report was saved under
    (policy.py auto-stamps this to the creator's own company for ordinary HR; only a group
    administrator can leave it empty, which here means every company, same as when they run it
    themselves) -- never to "whoever happens to be signed in when the tick fires"."""
    co_id = report_def.get("companyId")
    if co_id:
        return _rows_for(conn, report_def, {co_id})
    # no company: the group administrator's own group, never the companies that registered themselves
    return _rows_for(conn, report_def, {r[0] for r in conn.execute(text("SELECT id FROM companies"))} - repo.registered_companies(conn))


def to_excel(rows: list[dict], columns: list[str]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(columns)
    for r in rows:
        ws.append([r.get(c) for c in columns])
    for i, c in enumerate(columns, start=1):
        width = max(10, min(40, len(c) + 2, max((len(str(r.get(c) or "")) for r in rows), default=0) + 2))
        ws.column_dimensions[get_column_letter(i)].width = width
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------- scheduling
def _due(sch: dict, now: datetime) -> bool:
    if not sch.get("active", True):
        return False
    last = sch.get("lastSentAt")
    cadence = sch.get("cadence") or {}
    kind, hour = cadence.get("type") or "daily", int(cadence.get("hour") or 8)
    if now.hour != hour:
        return False
    if not last:
        return True
    last_dt = datetime.fromtimestamp(last / 1000)
    if kind == "daily":
        return now.date() > last_dt.date()
    if kind == "weekly":
        return now.date() > last_dt.date() and now.weekday() == int(cadence.get("dayOfWeek") or 0)
    if kind == "monthly":
        return now.date() > last_dt.date() and now.day == min(int(cadence.get("dayOfMonth") or 1), 28)
    return False


def _run_schedule(conn, sch: dict, send) -> None:
    rd = repo.get_records(conn, "reportDefs", [sch.get("reportDefId")]).get(sch.get("reportDefId"))
    if not rd:
        raise ValueError("the saved report this was scheduled from no longer exists")
    cols = columns_for(rd)
    rows = run_unattended(conn, rd)
    data = to_excel(rows, cols)
    to = [r for r in (sch.get("recipients") or []) if r]
    if not to:
        return
    subject, body = email_templates.render(conn, sch.get("companyId"), "report.scheduled",
                                            {"name": "there", "reportName": rd.get("name") or "Report", "when": datetime.now().strftime("%d %b %Y %H:%M"), "rowCount": len(rows)})
    name = f"{(rd.get('name') or 'report').replace(' ', '_')}.xlsx"
    (send or mailer.send)(to, subject, body, attachments=[(name, data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")])


def _all_schedules(conn) -> list:
    return [repo.loads(d) for d in conn.execute(text(f"SELECT data FROM {repo.BY_NAME['reportSchedules'].table}")).scalars()]


def tick(engine, now: datetime | None = None, send=None) -> list:
    now = now or datetime.now()
    done = []
    with engine.begin() as conn:
        for sch in _all_schedules(conn):
            if not _due(sch, now):
                continue
            try:
                _run_schedule(conn, sch, send)
                sch = {**sch, "lastSentAt": int(now.timestamp() * 1000), "lastError": None}
            except Exception as e:  # noqa: BLE001 - one bad schedule must not stop the others
                log.warning("Report schedule %s failed: %s", sch.get("id"), e)
                sch = {**sch, "lastError": str(e)[:500]}
            repo.upsert(conn, "reportSchedules", [sch], None)
            done.append(sch["id"])
        if done:
            repo.bump_rev(conn)
    return done


def _today() -> datetime:
    return datetime.now()


def start(engine, send=None):
    def loop():
        time.sleep(30)
        while True:
            try:
                tick(engine, _today(), send)
            except Exception as e:  # noqa: BLE001
                log.warning("Report scheduler tick failed: %s", e)
            time.sleep(max(1, int(os.getenv("REPORT_TICK_MIN", "60"))) * 60)
    threading.Thread(target=loop, name="report-schedules", daemon=True).start()
