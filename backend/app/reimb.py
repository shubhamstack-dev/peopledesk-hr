"""
PeopleDesk 2.15: reimbursement runs.

Approved expense claims are paid together on the company's reimbursement cycle, set by HR on the company record
(`reimb`):

    on          the cycle is in use
    mode        "payroll": paid with the next open salary month as a reimbursement (pay component 1900, not taxed);
                "bank":    a separate bank transfer; Finance downloads the bank advice and records the payment
    freq        "monthly" (on `day`, 1 to 28, or 31 for the last day), "fortnightly" (the 15th and the last day),
                or "weekly" (on `weekday`, 1 Monday to 7 Sunday)
    cutoffDays  claims approved at least this many days before the run day go in it
    auto        the server makes the run on the run day; otherwise Finance presses Run now
    notify      e-mail each employee what is being paid
    since       the date the cycle was set up: earlier run days are not made up

A run is one record in `reimbRuns`. Each claim in it carries `reimbRunId` and `reimbRunNo`. In payroll mode the claims
are paid when the run is made (a pay input per employee); in bank mode they stay approved until Finance records the
transfer, and are then paid.

The same functions serve Run now (main.py) and the automatic runs (tick(), started with the API).
"""
import calendar
import logging
import os
import threading
import time
import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import text

from . import email_templates, repo

log = logging.getLogger("peopledesk")
COMP = {"code": "1900", "name": "Expense reimbursement", "kind": "earning", "calc": "input", "value": 0, "order": 7,
        "taxable": False, "prorate": False, "esi": False, "wages": False, "sapWT": "1900"}
FREQS = ("monthly", "fortnightly", "weekly")


class Problem(Exception):
    pass


# ---------------------------------------------------------------- the cycle
def _last_day(y: int, m: int) -> int:
    return calendar.monthrange(y, m)[1]


def run_days(cfg: dict, start: date, end: date) -> list:
    """The run days of the cycle from start to end, inclusive."""
    out, d = [], start
    freq = cfg.get("freq") if cfg.get("freq") in FREQS else "monthly"
    while d <= end:
        last = _last_day(d.year, d.month)
        if freq == "monthly":
            day = int(cfg.get("day") or 31)
            hit = d.day == (last if day >= 29 else max(1, day))
        elif freq == "fortnightly":
            hit = d.day in (15, last)
        else:
            hit = d.isoweekday() == (int(cfg.get("weekday") or 5))
        if hit:
            out.append(d)
        d += timedelta(days=1)
    return out


def last_run_day(cfg: dict, today: date):
    """The latest run day on or before today (not before the cycle was set up), or None."""
    since = _date(cfg.get("since")) or today
    days = run_days(cfg, max(since, today - timedelta(days=40)), today)
    return days[-1] if days else None


def next_run_day(cfg: dict, today: date):
    days = run_days(cfg, today, today + timedelta(days=40))
    return days[0] if days else None


def _date(v):
    try:
        return date.fromisoformat(str(v)[:10]) if v else None
    except ValueError:
        return None


def _ym_add(ym: str, n: int) -> str:
    y, m = int(ym[:4]), int(ym[5:7]) - 1 + n
    return f"{y + m // 12:04d}-{m % 12 + 1:02d}"


# ---------------------------------------------------------------- what goes in a run
def approved_at(c: dict) -> int:
    """When the claim was fully approved (ms): the last approval, or when it was sent if nobody had to approve it."""
    ats = [int(s.get("at") or 0) for s in c.get("steps") or [] if (s or {}).get("decision") == "approved"]
    return max(ats) if ats else int(c.get("submittedAt") or c.get("at") or 0)


def claim_total(c: dict) -> float:
    return round(sum(float(x.get("amount") or 0) for x in c.get("lines") or []), 2)


def due_claims(conn, company_id: str, run_day: date, cutoff_days: int) -> list:
    """Approved claims not yet in a run and not paid, approved by the cut-off."""
    limit = datetime.combine(run_day - timedelta(days=max(0, cutoff_days)), datetime.max.time()).timestamp() * 1000
    out = []
    for c in repo.records_where(conn, "expenseClaims", "company_id", company_id):
        if c.get("status") == "approved" and not c.get("reimbRunId") and claim_total(c) > 0 and approved_at(c) <= limit:
            out.append(c)
    return sorted(out, key=lambda c: (str(c.get("empId")), str(c.get("no"))))


def pay_month(conn, company_id: str, run_day: date) -> str:
    """The salary month the reimbursement is paid in: the run's month, or the first month after the locked ones."""
    locked = sorted(r.get("month") for r in repo.records_where(conn, "payRuns", "company_id", company_id)
                    if r.get("status") == "locked" and r.get("month"))
    m = run_day.isoformat()[:7]
    nxt = _ym_add(locked[-1], 1) if locked else m
    return max(m, nxt)


def _run_no(conn, co: dict, run_day: date) -> str:
    base = f"RB-{co.get('code') or 'CO'}-{run_day.strftime('%Y%m%d')}"
    taken = {r.get("no") for r in repo.records_where(conn, "reimbRuns", "company_id", co["id"])}
    n, no = 1, base
    while no in taken:
        n += 1
        no = f"{base}-{n}"
    return no


def _log(c: dict, by: str, what: str, note: str = ""):
    c["log"] = [*(c.get("log") or []), {"at": int(time.time() * 1000), "by": by or "", "what": what, "note": note}]


def make_run(conn, co: dict, run_day: date, by: str = "", auto: bool = False, period: str = "", only=None, not_of: str = ""):
    """Makes the run for the company and returns it, or None when no claim is due. `only` limits it to those claim ids;
    `not_of` leaves out that employee's claims (Finance does not pay its own claims)."""
    cfg = co.get("reimb") or {}
    mode = "payroll" if cfg.get("mode") == "payroll" else "bank"
    claims = due_claims(conn, co["id"], run_day, 0 if not auto else int(cfg.get("cutoffDays") or 0))
    if only is not None:
        claims = [c for c in claims if c["id"] in set(only)]
    if not_of:
        claims = [c for c in claims if c.get("empId") != not_of]
    if not claims:
        return None
    now = int(time.time() * 1000)
    rid = f"rb-{co['id']}-{period}" if auto and period else uuid.uuid4().hex[:16]
    no = _run_no(conn, co, run_day)
    month = pay_month(conn, co["id"], run_day) if mode == "payroll" else ""
    lines = [{"claimId": c["id"], "claimNo": c.get("no") or "", "empId": c.get("empId"), "amount": claim_total(c), "title": c.get("title") or ""} for c in claims]
    run = {"id": rid, "companyId": co["id"], "no": no, "runDate": run_day.isoformat(), "periodKey": period or run_day.isoformat(), "mode": mode,
           "status": "posted" if mode == "payroll" else "scheduled", "auto": auto, "createdAt": now, "createdBy": by or "",
           "payMonth": month, "lines": lines, "total": round(sum(x["amount"] for x in lines), 2), "count": len(lines),
           "employees": len({x["empId"] for x in lines})}
    inputs = []
    for c in claims:
        c["reimbRunId"], c["reimbRunNo"] = rid, no
        if mode == "payroll":
            c.update(status="paid", payMonth=month, paidAt=now)
            _log(c, by, f"Paid with salary in reimbursement run {no}", month)
        else:
            _log(c, by, f"In reimbursement run {no}", f"bank transfer from {run_day.isoformat()}")
    if mode == "payroll":
        by_emp: dict = {}
        for c in claims:
            by_emp.setdefault(c.get("empId"), []).append(c)
        for emp, cs in by_emp.items():
            inputs.append({"id": uuid.uuid4().hex[:16], "companyId": co["id"], "empId": emp, "month": month, "code": COMP["code"],
                           "amount": int(sum(claim_total(c) for c in cs) + 0.5), "note": f"Reimbursement run {no}: {', '.join(c.get('no') or '' for c in cs)}",
                           "claimIds": [c["id"] for c in cs], "reimbRunId": rid})
        comps = repo.records_where(conn, "payComps", "company_id", co["id"])
        if not any(x.get("code") == COMP["code"] for x in comps):
            repo.upsert(conn, "payComps", [{"id": uuid.uuid4().hex[:16], "companyId": co["id"], **COMP}], by or None)
    repo.upsert(conn, "reimbRuns", [run], by or None)
    repo.upsert(conn, "expenseClaims", claims, by or None)
    if inputs:
        repo.upsert(conn, "payInputs", inputs, by or None)
    repo.audit_add(conn, "Reimbursement run", f"{no}: {len(claims)} claims, ₹{run['total']:,.0f}{' (automatic)' if auto else ''}", by or None, module="expenses")
    repo.bump_rev(conn)
    return run


def mark_paid(conn, run: dict, ref: str, paid_on: str, by: str) -> dict:
    """Bank mode: the transfer is made. The run and its claims are paid."""
    if run.get("status") != "scheduled":
        raise Problem("This run is not waiting for a bank transfer.")
    ref = (ref or "").strip()[:80]
    if not ref:
        raise Problem("Enter the bank reference (UTR or batch number).")
    d = _date(paid_on)
    if not d or d > date.today() + timedelta(days=1):
        raise Problem("Enter the date the transfer was made.")
    now = int(time.time() * 1000)
    claims = list(repo.get_records(conn, "expenseClaims", [x["claimId"] for x in run.get("lines") or []]).values())
    for c in claims:
        if c.get("status") == "approved" and c.get("reimbRunId") == run["id"]:
            c.update(status="paid", paidRef=ref, paidAt=now, paidOn=d.isoformat())
            _log(c, by, f"Paid by bank transfer, reimbursement run {run.get('no')}", ref)
    run.update(status="paid", paidRef=ref, paidOn=d.isoformat(), paidAt=now, paidBy=by)
    repo.upsert(conn, "reimbRuns", [run], by)
    repo.upsert(conn, "expenseClaims", claims, by)
    repo.audit_add(conn, "Reimbursement run paid", f"{run.get('no')}: {ref}", by, module="expenses")
    repo.bump_rev(conn)
    return run


def mails(conn, run: dict, co: dict) -> list:
    """(to, subject, text) for each employee in the run."""
    emps = repo.get_records(conn, "employees", list({x["empId"] for x in run.get("lines") or []}))
    out = []
    for emp_id, e in emps.items():
        mine = [x for x in run["lines"] if x["empId"] == emp_id]
        to = e.get("email") or e.get("personalEmail")
        if not to:
            continue
        total = sum(x["amount"] for x in mine)
        how = (f"with your salary for {datetime.strptime(run['payMonth'], '%Y-%m').strftime('%B %Y')}" if run["mode"] == "payroll"
               else f"by bank transfer to your salary account, from {run['runDate']}")
        subject, body = email_templates.render(conn, co.get("id"), "reimb.paid", {
            "firstName": e.get("firstName") or "", "how": how, "total": f"{total:,.0f}", "runNo": run["no"], "companyName": co.get("name") or "",
            "claims": [{"no": x["claimNo"], "title": x["title"], "amount": f"{x['amount']:,.0f}"} for x in mine]})
        out.append((to, subject, body))
    return out


# ---------------------------------------------------------------- automatic runs
def _companies(conn) -> list:
    return [repo.loads(d) for d in conn.execute(text("SELECT data FROM companies")).scalars()]


def tick(engine, today: date | None = None, send=None) -> list:
    """Makes the runs that are due today for companies with automatic runs. Returns the runs made."""
    made = []
    today = today or _today()
    with engine.begin() as conn:
        got = conn.execute(text("SELECT GET_LOCK('peopledesk_reimb', 0)")).scalar() if engine.dialect.name == "mysql" else 1
        if not got:
            return made                # another worker is on it
        try:
            for co in _companies(conn):
                cfg = co.get("reimb") or {}
                if not (cfg.get("on") and cfg.get("auto")):
                    continue
                day = last_run_day(cfg, today)
                if not day:
                    continue
                key = day.isoformat()
                if any(r.get("periodKey") == key and r.get("auto") for r in repo.records_where(conn, "reimbRuns", "company_id", co["id"])):
                    continue
                run = make_run(conn, co, day, auto=True, period=key)
                if run:
                    made.append(run)
                    log.info("Reimbursement run %s made: %s claims", run["no"], run["count"])
                    if cfg.get("notify") and send:
                        for to, subj, body in mails(conn, run, co):
                            try:
                                send([to], subj, body)
                            except Exception as e:  # noqa: BLE001
                                log.warning("Reimbursement mail to %s failed: %s", to, e)
        finally:
            if engine.dialect.name == "mysql":
                conn.execute(text("SELECT RELEASE_LOCK('peopledesk_reimb')"))
    return made


def _today() -> date:
    try:
        from zoneinfo import ZoneInfo
        from .config import APP_TZ
        return datetime.now(ZoneInfo(APP_TZ)).date()
    except Exception:  # noqa: BLE001
        return date.today()


def start(engine, send=None):
    """Checks for due runs every REIMB_TICK_MIN minutes (15), in a background thread. REIMB_AUTO=false turns it off."""
    if os.getenv("REIMB_AUTO", "true").lower() == "false":
        return

    def loop():
        time.sleep(30)
        while True:
            try:
                tick(engine, send=send)
            except Exception as e:  # noqa: BLE001
                log.warning("Automatic reimbursement runs: %s", e)
            time.sleep(max(1, int(os.getenv("REIMB_TICK_MIN", "15"))) * 60)

    threading.Thread(target=loop, name="reimbursement-runs", daemon=True).start()
