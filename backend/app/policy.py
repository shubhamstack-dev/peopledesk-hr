"""
Who may see and change what.

Roles come from the employee record: "super" (group administrator), "hr" (HR
administrator for their own company plus any in hrCompanies) and "employee".
Anyone with people reporting to them is also a manager.

Reading: everyone receives the records the screens need to work (names, the
reporting line, leave and attendance for approvals), but salary, bank,
statutory numbers, personal contact details, other people's payslips, tax
declarations and the activity log are removed unless the reader is HR for
that company or it is their own record.

Writing: HR may change anything in the companies they look after. Others may
change their own requests and those of people in their reporting line, and
cannot approve their own requests, change their access, salary or job record.
"""
from dataclasses import dataclass, field

from . import repo

# Collections only HR (for the record's company) may change
HR_ONLY = {"companies", "depts", "desigs", "grades", "locations", "holidays", "leaveTypes", "shifts",
           "payComps", "payInputs", "payRuns", "cycles", "posts", "shiftPatterns"}
# Collections employees and managers change through everyday flows
WORKFLOW = {"leaveReqs", "leaveAdj", "punches", "regs", "goals", "reviews", "feedback", "declarations",
            "otRecs", "exits", "reqs", "cands", "apps", "interviews"}
# Requests where the person concerned may not approve their own
SELF_APPROVAL = {"leaveReqs", "regs", "otRecs", "leaveAdj", "goals"}
APPROVED = {"approved"}

# Employee fields hidden from people who are not HR for that company (and not the person)
SENSITIVE_EMP = {"salaryHist": [], "salaryOverrides": {}, "pan": "", "aadhaar": "", "uan": "", "pfNo": "",
                 "esiNo": "", "esiRegDate": "", "esiDispensary": "", "bankName": "", "bankAcc": "", "ifsc": "",
                 "payMode": "", "vpfPct": "", "address": "", "personalEmail": "", "emergency": "", "marital": "",
                 "blood": "", "gratuityFrom": "", "googleId": ""}
# Employee fields a person may not change on their own record
PROTECTED_SELF = {"id", "role", "companyId", "hrCompanies", "status", "blocked", "empNo", "email", "managerId",
                  "salaryHist", "salaryOverrides", "doj", "exit", "stints", "gratuityFrom", "gradeId", "desigId",
                  "deptId", "locationId", "empType", "probationEnd", "attGroup", "otEligible", "shiftId", "source",
                  "pfOn", "epsOn", "esiOn", "ptOn", "lwfOn", "patternId", "patternFrom"}
# Employee fields a manager may change for someone in their reporting line (resignation flow)
MANAGER_MAY = {"exit", "history", "status"}


@dataclass
class Ctx:
    me: dict
    emps: dict                       # id -> employee
    hr_scope: set | None = None      # None means every company (group administrator)
    line: set = field(default_factory=set)

    @property
    def id(self):
        return self.me["id"]

    @property
    def is_super(self):
        return self.me.get("role") == "super"

    def is_hr_for(self, company_id) -> bool:
        if self.is_super:
            return True
        return bool(self.hr_scope) and company_id in self.hr_scope

    @property
    def is_hr(self):
        return self.is_super or bool(self.hr_scope)


def make_ctx(me: dict, emps: dict) -> Ctx:
    role = me.get("role")
    scope = None if role == "super" else ({me.get("companyId"), *(me.get("hrCompanies") or [])} if role == "hr" else set())
    scope = None if scope is None else {x for x in scope if x}
    by_mgr: dict = {}
    for e in emps.values():
        if e.get("managerId") and e.get("status") != "exited":
            by_mgr.setdefault(e["managerId"], []).append(e["id"])
    line, stack = set(), [me["id"]]
    while stack:
        for r in by_mgr.get(stack.pop(), []):
            if r not in line:
                line.add(r)
                stack.append(r)
    return Ctx(me=me, emps=emps, hr_scope=scope, line=line)


# ---------------------------------------------------------------- reading
def redact_state(st: dict, ctx: Ctx) -> dict:
    if ctx.is_super:
        return st
    emp_co = {e["id"]: e.get("companyId") for e in st["employees"]}
    sees_all = lambda emp_id: emp_id == ctx.id or ctx.is_hr_for(emp_co.get(emp_id))  # noqa: E731

    for e in st["employees"]:
        if not sees_all(e["id"]):
            for k, blank in SENSITIVE_EMP.items():
                if k in e:
                    e[k] = blank
            if isinstance(e.get("dob"), str) and len(e["dob"]) == 10:
                e["dob"] = "1900" + e["dob"][4:]          # keeps birthdays on the home page, hides age
            for s in e.get("stints") or []:
                s.pop("ctc", None)
    for run in st["payRuns"]:
        if not ctx.is_hr_for(run.get("companyId")):
            run["results"] = {k: v for k, v in (run.get("results") or {}).items() if k == ctx.id}
            run["skipped"] = []
    st["payInputs"] = [x for x in st["payInputs"] if sees_all(x.get("empId")) and (x.get("empId") == ctx.id or ctx.is_hr_for(x.get("companyId")))]
    st["declarations"] = [x for x in st["declarations"] if sees_all(x.get("empId"))]
    st["leaveAdj"] = [x for x in st["leaveAdj"] if x.get("empId") == ctx.id or x.get("empId") in ctx.line or ctx.is_hr_for(emp_co.get(x.get("empId")))]
    st["audit"] = [a for a in st["audit"] if ctx.is_hr_for(emp_co.get(a.get("by")))] if ctx.is_hr else []
    s = st.get("settings") or {}
    st["settings"] = s if ctx.is_hr else {k: s.get(k) for k in ("googleClientId", "allowDemo", "allowPassword", "idleMin") if k in s}
    return st


# ---------------------------------------------------------------- writing
class Rejected(Exception):
    pass


def record_company(conn, coll: str, rec: dict, ctx: Ctx):
    if not rec:
        return None
    if coll == "companies":
        return rec.get("id")
    if rec.get("companyId"):
        return rec["companyId"]
    for k in ("empId", "to", "from"):
        e = ctx.emps.get(rec.get(k))
        if e:
            return e.get("companyId")
    if coll == "apps" and rec.get("reqId"):
        return repo.lookup_company(conn, "job_requisitions", rec["reqId"])
    if coll == "interviews" and rec.get("appId"):
        req_id = repo.lookup_field(conn, "applications", rec["appId"], "req_id")
        return repo.lookup_company(conn, "job_requisitions", req_id) if req_id else None
    return None


def check_upsert(conn, coll: str, new: dict, old: dict | None, ctx: Ctx) -> dict:
    """Returns the record to store, or raises Rejected."""
    if ctx.is_super:
        return new
    co_new, co_old = record_company(conn, coll, new, ctx), record_company(conn, coll, old, ctx)
    hr_ok = all(c is None or ctx.is_hr_for(c) for c in (co_new, co_old)) and ctx.is_hr

    if coll == "employees":
        return _employee(new, old, ctx, hr_ok)

    if hr_ok:
        return new
    if coll in HR_ONLY or coll not in WORKFLOW:
        raise Rejected("only HR can change this")
    own_co = ctx.me.get("companyId")
    if any(c not in (None, own_co) for c in (co_new, co_old)):
        raise Rejected("belongs to another company")

    subject = new.get("empId") or (old or {}).get("empId")
    if coll == "feedback":
        if not old and new.get("from") != ctx.id:
            raise Rejected("feedback can only be sent as yourself")
        return new
    if coll == "declarations" and subject != ctx.id:
        raise Rejected("only your own tax declaration")
    if subject and subject != ctx.id and subject not in ctx.line:
        raise Rejected("not in your reporting line")
    if coll in SELF_APPROVAL and subject == ctx.id:
        was = (old or {}).get("status")
        now = new.get("status")
        if now in APPROVED and was != now:
            no_manager = not ctx.emps.get(ctx.me.get("managerId"))
            if not (coll == "goals" and no_manager):
                raise Rejected("you cannot approve your own request")
    return new


def _employee(new: dict, old: dict | None, ctx: Ctx, hr_ok: bool) -> dict:
    if hr_ok:
        if not ctx.is_super:
            if (new.get("role") == "super") != ((old or {}).get("role") == "super"):
                raise Rejected("only the group administrator can grant or remove group access")
            extra = set(new.get("hrCompanies") or []) - (ctx.hr_scope or set())
            if extra:
                raise Rejected("cannot give HR access to a company you do not manage")
        return new
    if not old:
        raise Rejected("only HR can add employees")
    if new["id"] == ctx.id:
        merged = dict(new)
        for k in PROTECTED_SELF:
            if k in old:
                merged[k] = old[k]
            else:
                merged.pop(k, None)
        return merged
    if new["id"] in ctx.line:
        merged = dict(old)
        for k in MANAGER_MAY:
            if k in new:
                merged[k] = new[k]
        if merged.get("status") == "exited" and old.get("status") != "exited":
            raise Rejected("only HR can complete an exit")
        return merged
    raise Rejected("you cannot change this employee")


def check_delete(conn, coll: str, old: dict, ctx: Ctx):
    if ctx.is_super:
        return
    co = record_company(conn, coll, old, ctx)
    if ctx.is_hr and (co is None or ctx.is_hr_for(co)):
        if coll == "employees" and old.get("role") == "super":
            raise Rejected("only the group administrator can remove a group administrator")
        return
    if coll in HR_ONLY or coll not in WORKFLOW or coll == "employees":
        raise Rejected("only HR can delete this")
    subject = old.get("empId")
    owner = old.get("by") or old.get("from") or old.get("createdBy")
    if subject == ctx.id or owner == ctx.id or (subject and subject in ctx.line):
        return
    raise Rejected("not yours to delete")


def check_singleton(k: str, ctx: Ctx):
    if k == "seq":
        return
    if not ctx.is_hr:
        raise Rejected("only HR can change settings")


def check_roster(emp_id: str, ctx: Ctx):
    e = ctx.emps.get(emp_id)
    if ctx.is_super or (e and ctx.is_hr_for(e.get("companyId"))) or emp_id in ctx.line:
        return
    raise Rejected("you can only roster your own team")
