"""
PeopleDesk 2.7: workforce rules enforced on the server.

- Background on the employee record (previous jobs, education, awards, references). Employees keep their own
  entries; only HR records whether an entry was checked, and an entry the employee changes has to be checked again.
  Line managers see their people's experience, education and awards, without previous salary or references.
- Standard lists (institutions, qualifications, employers) are kept by HR. Employees may only propose a new entry,
  which HR adds to the list, maps to an existing entry, or keeps off the list.
- Attendance locked for payroll. A payroll run locks attendance for its month, up to a day, for its register (own
  employees or contract workers). Punches, attendance and shift-change requests, leave and the roster for those
  days cannot change until HR unlocks attendance on the run.
- Shift changes need the notice the company sets (hours before the shift starts). HR may override it when the
  policy allows, and a change the employee asked for and had approved can be applied at any time.
"""
import time
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import text

from . import repo
from .config import APP_TZ

try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo(APP_TZ)
except Exception:  # noqa: BLE001  (no time zone database in the container: India)
    TZ = timezone(timedelta(minutes=330))


class Problem(Exception):
    pass


BG_LISTS = ("prevJobs", "education", "awards", "references")
MASTER_KINDS = {"institution", "qualification", "employer"}
LOCKED_COLLS = {"punches", "regs", "leaveReqs"}
# fields whose change matters for attendance (a log entry or a note may still be added after the lock)
LOCK_FIELDS = {"punches": None, "regs": ("status", "in", "out", "shiftId", "date", "to", "applied", "empId"),
               "leaveReqs": ("status", "from", "to", "half", "typeId", "days", "empId")}


def dmy(iso: str) -> str:
    return f"{iso[8:10]}-{iso[5:7]}-{iso[:4]}" if isinstance(iso, str) and len(iso) >= 10 else str(iso)


def register_of(emp: dict | None) -> str:
    """Own employees and third-party contract workers have separate attendance registers and payrolls."""
    if not emp:
        return "own"
    cat = emp.get("workerCategory")
    return "contract" if cat == "contract" or (not cat and emp.get("contractorId")) else "own"


# ---------------------------------------------------------------- background on the employee record
def _content(item: dict) -> dict:
    return {k: v for k, v in (item or {}).items() if k != "verify"}


def keep_verification(new_emp: dict, old_emp: dict) -> dict:
    """An employee saving their own record: HR's check stays on entries they did not change and is dropped from
    entries they changed or added, so nobody marks their own background as verified."""
    for k in BG_LISTS:
        items = new_emp.get(k)
        if items is None:
            continue
        if not isinstance(items, list):
            raise Problem("background details are not in the right form")
        olds = {i.get("id"): i for i in (old_emp.get(k) or []) if isinstance(i, dict)}
        out = []
        for it in items:
            if not isinstance(it, dict):
                continue
            it = dict(it)
            it.pop("verify", None)
            o = olds.get(it.get("id"))
            if o and o.get("verify") and _content(o) == _content(it):
                it["verify"] = o["verify"]
            out.append(it)
        new_emp[k] = out
    return new_emp


def _strip_notes(items):
    out = []
    for it in items or []:
        if isinstance(it, dict) and isinstance(it.get("verify"), dict):
            it = {**it, "verify": {k: v for k, v in it["verify"].items() if k in ("status", "at")}}
        out.append(it)
    return out


def redact_employee(e: dict, rel: str):
    """rel: 'self' (not HR), 'line' (a manager above them) or 'other'. HR receives everything."""
    if rel == "self":
        for k in BG_LISTS:
            if k in e:
                e[k] = _strip_notes(e[k])             # HR's notes from reference checks stay with HR
        return
    if rel == "line":
        e["references"] = []
        e["prevJobs"] = [{k: v for k, v in j.items() if k not in ("lastCtc", "reason")} for j in _strip_notes(e.get("prevJobs")) if isinstance(j, dict)]
        for k in ("education", "awards"):
            if k in e:
                e[k] = _strip_notes(e[k])
    else:
        for k in BG_LISTS:
            if k in e:
                e[k] = []
    ann = e.get("anniversary")
    if isinstance(ann, str) and len(ann) == 10 and e.get("shareAnniversary") is not False:
        e["anniversary"] = "1900" + ann[4:]          # the day for greetings, not the year
    elif "anniversary" in e:
        e["anniversary"] = ""


# ---------------------------------------------------------------- standard lists
def check_master(new: dict, old: dict | None, me_id: str) -> dict:
    """Someone who is not HR may only propose a new entry, as themselves."""
    if old:
        raise Problem("only HR changes the standard lists")
    if new.get("kind") not in MASTER_KINDS:
        raise Problem("unknown list")
    name = " ".join(str(new.get("name") or "").split())
    if not 2 <= len(name) <= 150:
        raise Problem("give the name in full")
    if new.get("status") != "proposed" or new.get("proposedBy") != me_id:
        raise Problem("only HR adds to the standard lists; a new name is proposed for HR to accept")
    return {**new, "name": name}


def visible_masters(items: list, me_id: str) -> list:
    return [x for x in items if x.get("status") == "approved" or x.get("proposedBy") == me_id]


# ---------------------------------------------------------------- attendance locked for payroll
def _month_end(ym: str) -> str:
    y, m = int(ym[:4]), int(ym[5:7])
    return (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)).isoformat()


def _truthy(v) -> bool:
    return v is True or v == 1 or str(v).strip('"').lower() in ("true", "1")


def _days(coll: str, r: dict) -> list:
    if coll == "punches":
        return [r.get("date")]
    a, b = (r.get("date"), r.get("to")) if coll == "regs" else (r.get("from"), r.get("to"))
    if not isinstance(a, str) or len(a) < 10:
        return []
    if not isinstance(b, str) or len(b) < 10 or b < a:
        return [a]
    out, d, end = [], date.fromisoformat(a[:10]), date.fromisoformat(b[:10])
    while d <= end and len(out) < 400:
        out.append(d.isoformat())
        d += timedelta(days=1)
    return out


class Guard:
    """Checks for one save: attendance locks and shift-change notice, with what it reads cached."""

    def __init__(self, conn):
        self.conn = conn
        self._runs: dict = {}
        self._cos: dict = {}
        self._shifts: dict = {}

    def forget_runs(self):
        self._runs.clear()

    def _locks(self, co_id) -> dict:
        if co_id not in self._runs:
            rows = self.conn.execute(text(
                "SELECT month, status, JSON_UNQUOTE(JSON_EXTRACT(data, '$.register')), JSON_EXTRACT(data, '$.attLocked'), "
                "JSON_UNQUOTE(JSON_EXTRACT(data, '$.attLockUpTo')) FROM pay_runs WHERE company_id=:c"), {"c": co_id}).fetchall()
            d = {}
            for month, status, reg, att, upto in rows:
                if not month or not (status == "locked" or _truthy(att)):
                    continue
                end = _month_end(str(month))
                u = upto if isinstance(upto, str) and len(upto) == 10 else end
                key = (reg if reg in ("own", "contract") else "own", str(month))
                d[key] = max(d.get(key, ""), min(u, end))
            self._runs[co_id] = d
        return self._runs[co_id]

    def locked_until(self, emp: dict | None, day) -> str | None:
        if not emp or not isinstance(day, str) or len(day) < 10:
            return None
        u = self._locks(emp.get("companyId")).get((register_of(emp), day[:7]))
        return u if u and day[:10] <= u else None

    def check_record(self, coll: str, new: dict | None, old: dict | None, emps: dict):
        """Punches, attendance and shift-change requests and leave on locked days cannot change."""
        if coll not in LOCKED_COLLS:
            return
        if old and new is not None:
            f = LOCK_FIELDS[coll]
            if (new == old) if f is None else all(new.get(k) == old.get(k) for k in f):
                return
        for rec in (new, old):
            if not rec:
                continue
            emp = emps.get(rec.get("empId"))
            for d in _days(coll, rec):
                u = self.locked_until(emp, d)
                if u:
                    raise Problem(f"attendance up to {dmy(u)} is locked for payroll; HR unlocks it on the payroll run")

    # ------------------------------------------------ the roster
    def _company(self, co_id) -> dict:
        if co_id not in self._cos:
            self._cos[co_id] = (repo.get_records(self.conn, "companies", [co_id]) or {}).get(co_id) or {}
        return self._cos[co_id]

    def _shift(self, sid) -> dict | None:
        if sid and sid not in self._shifts:
            self._shifts[sid] = (repo.get_records(self.conn, "shifts", [sid]) or {}).get(sid)
        return self._shifts.get(sid) if sid else None

    def _start(self, emp: dict, day: str, value) -> float:
        """When the work of a day starts for a roster value (a shift id, WO, or nothing: the default shift)."""
        d = date.fromisoformat(day[:10])
        midnight = datetime(d.year, d.month, d.day, tzinfo=TZ).timestamp()
        if value == "WO":
            return midnight
        sh = self._shift(value or emp.get("shiftId"))
        if not sh:
            return midnight
        if not value and ((d.weekday() + 1) % 7) in (sh.get("weeklyOff") or []):
            return midnight
        try:
            h, m = (int(x) for x in str(sh.get("start") or "0:0").split(":")[:2])
        except ValueError:
            return midnight
        return midnight + h * 3600 + m * 60

    def _effective(self, emp: dict, day: str, value):
        """What the person works that day: a shift id, or WO."""
        if value:
            return value
        sh = self._shift(emp.get("shiftId"))
        if sh and ((date.fromisoformat(day[:10]).weekday() + 1) % 7) in (sh.get("weeklyOff") or []):
            return "WO"
        return emp.get("shiftId") or ""

    def _employee_asked(self, emp_id: str, day: str, value) -> bool:
        """A shift change the employee asked for themselves, approved through the workflow."""
        for d in self.conn.execute(text("SELECT data FROM attendance_regularisations WHERE emp_id=:e AND day=:d"), {"e": emp_id, "d": day}).scalars():
            r = repo.loads(d)
            if r.get("type") == "shift" and r.get("status") == "approved" and r.get("by") in (None, "", emp_id) and (r.get("shiftId") or None) == (value or None):
                return True
        return False

    def check_roster(self, emp_id: str, day: str, value, emps: dict, is_hr: bool):
        emp = emps.get(emp_id)
        if not emp or not isinstance(day, str) or len(day) != 10:
            raise Problem("unknown roster day")
        u = self.locked_until(emp, day)
        if u:
            raise Problem(f"attendance up to {dmy(u)} is locked for payroll; the roster for those days cannot change")
        pol = self._company(emp.get("companyId")).get("shiftPolicy") or {}
        try:
            notice = float(pol.get("noticeHrs") or 0)
        except (TypeError, ValueError):
            notice = 0
        if notice <= 0 or (is_hr and pol.get("hrOverride") is not False):
            return
        old = self.conn.execute(text("SELECT value FROM roster WHERE emp_id=:e AND day=:d"), {"e": emp_id, "d": day}).scalar()
        if self._effective(emp, day, old) == self._effective(emp, day, value) or self._employee_asked(emp_id, day, value):
            return
        if min(self._start(emp, day, old), self._start(emp, day, value)) < time.time() + notice * 3600:
            raise Problem(f"shift changes need {notice:g} hours' notice before the shift starts; {dmy(day)} is too soon")
