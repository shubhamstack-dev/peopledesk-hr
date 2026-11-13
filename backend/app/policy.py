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

Teams (2.10), given by HR on the employee record (`teams`), for their own company:
- "it" and "admin" keep their own kinds of asset (IT: laptops, phones, TVs; Administration: ID cards, access
  cards) and add, issue and take back assets of those kinds.
- "finance" runs payroll (payroll runs, inputs, tax declarations, statutory registers) and checks and pays
  expense claims. Finance sees what payroll needs of each employee (salary, bank, PAN, UAN, ESI, date of birth),
  not their address, family or background.
"""
from dataclasses import dataclass, field

from sqlalchemy import text

from . import candform, comp, cportal, perf, recruit, repo, security_fields, training, workflow, workforce

# Collections only HR (for the record's company) may change
HR_ONLY = {"companies", "depts", "desigs", "grades", "locations", "holidays", "leaveTypes", "shifts",
           "payComps", "payInputs", "payRuns", "cycles", "posts", "shiftPatterns",
           "expenseCats", "perfTemplates", "onboardTemplates", "docTypes", "docTemplates", "compCycles", "contractors",
           "goalLib", "reimbRuns",
           "approverGroups", "emailTemplates", "reportDefs", "reportSchedules"}
# Performance meetings and succession plans follow their own rules (perf.py)
PERF = {"perfMeetings", "succession"}
# Compensation planning: budgets and recommendations follow their own rules (comp.py)
COMP = {"compBudgets", "compRecs"}
# Training: trainings are HR's, but internal trainers add content and mark completion; enrolments and feedback
# follow their own rules (training.py)
TRAIN = {"trainings", "trainingEnrols", "trainingFeedback"}
# Records shared by the people taking part in them (requester, approvers, department owners).
# Each carries a `participants` list of employee ids; approval steps carry `approverIds`.
PARTICIPANT = {"requests", "expenseClaims", "onboardings", "assets"}
FINAL_STATUSES = {"approved", "applied", "paid", "done", "completed", "returned"}
# Collections employees and managers change through everyday flows
WORKFLOW = {"leaveReqs", "leaveAdj", "punches", "regs", "goals", "reviews", "feedback", "declarations",
            "otRecs", "exits", "reqs", "cands", "apps", "interviews", "trainingNeeds"}
# Requests where the person concerned may not approve their own
SELF_APPROVAL = {"leaveReqs", "regs", "otRecs", "leaveAdj", "goals"}
APPROVED = {"approved"}

# Employee fields hidden from people who are not HR for that company (and not the person)
SENSITIVE_EMP = {"salaryHist": [], "salaryOverrides": {}, "pan": "", "aadhaar": "", "uan": "", "pfNo": "",
                 "esiNo": "", "esiRegDate": "", "esiDispensary": "", "bankName": "", "bankAcc": "", "ifsc": "",
                 "payMode": "", "vpfPct": "", "address": "", "personalEmail": "", "emergency": "", "marital": "",
                 "blood": "", "gratuityFrom": "", "googleId": "", "family": [], "documents": [], "addrCity": "", "addrState": "",
                 "addrPin": "", "addrCountry": "", "emergencyName": "", "emergencyRelation": "", "emergencyPhone": "", "mediclaim": []}
# Employee fields a person may not change on their own record
PROTECTED_SELF = {"id", "role", "companyId", "hrCompanies", "status", "blocked", "empNo", "email", "managerId",
                  "salaryHist", "salaryOverrides", "doj", "exit", "stints", "gratuityFrom", "gradeId", "desigId",
                  "deptId", "locationId", "empType", "probationEnd", "attGroup", "otEligible", "shiftId", "source",
                  "pfOn", "epsOn", "esiOn", "ptOn", "lwfOn", "patternId", "patternFrom", "rotFilledTo",
                  "workerCategory", "contractorId", "nightConsent", "teams",
                  "matrixManagerIds", "reportingHist", "gradeHist", "pendingMoves", "variableHist",
                  # statutory details change only through an approved request; letters are issued by HR
                  "pan", "aadhaar", "uan", "pfNo", "esiNo", "esiRegDate", "esiDispensary", "vpfPct", "documents",
                  "mediclaim"}
# Contract workers (employed through a contractor) do not see or handle pay and money here: payslips, salary,
# tax declarations, expense claims, leave encashment. Nor awards. Their own record arrives without these, and
# a save of it keeps what is stored.
CW_HIDDEN_SELF = {"salaryHist": [], "salaryOverrides": {}, "variableHist": [], "awards": []}
CW_NO_WRITE = {"expenseClaims", "declarations"}
CW_NO_REQUEST = {"encash"}
TEAMS = {"admin", "it", "finance"}
ASSET_TEAMS = {"admin", "it"}
# What finance sees of employees for payroll (others' records arrive without these)
FINANCE_SEES = {"salaryHist", "salaryOverrides", "pan", "aadhaar", "uan", "pfNo", "esiNo", "esiRegDate", "esiDispensary",
                "bankName", "bankAcc", "ifsc", "payMode", "vpfPct", "gratuityFrom", "addrState"}
FINANCE_WRITE = {"payRuns", "payInputs", "declarations"}
# An employee field finance may change (the tax regime, on the TDS pages)
FINANCE_MAY = {"taxRegime"}
# Employee fields a manager may change for someone in their reporting line (resignation flow, shift rotation)
MANAGER_MAY = {"exit", "history", "status", "patternId", "patternFrom", "rotFilledTo"}


@dataclass
class Ctx:
    me: dict
    emps: dict                       # id -> employee
    hr_scope: set | None = None      # None means every company of the group (group administrator)
    line: set = field(default_factory=set)
    private: set = field(default_factory=set)   # companies that registered themselves: outside the group administrator's reach

    @property
    def id(self):
        return self.me["id"]

    @property
    def is_super(self):
        return self.me.get("role") == "super"

    def is_hr_for(self, company_id) -> bool:
        if self.is_super:
            return company_id not in self.private
        return bool(self.hr_scope) and company_id in self.hr_scope

    @property
    def is_hr(self):
        return self.is_super or bool(self.hr_scope)

    @property
    def teams(self) -> set:
        return {t for t in (self.me.get("teams") or []) if t in TEAMS}

    def in_team(self, team: str, company_id) -> bool:
        """HR counts as every team. A team member acts for their own company only."""
        if self.is_hr_for(company_id):
            return True
        return team in self.teams and company_id is not None and company_id == self.me.get("companyId")

    def is_finance_for(self, company_id) -> bool:
        return self.in_team("finance", company_id)

    @property
    def is_contract_worker(self):
        """A third-party contract worker without HR access: no payslips, salary, awards or money matters here."""
        return not self.is_hr and workforce.register_of(self.me) == "contract"


def make_ctx(me: dict, emps: dict, private: set | None = None) -> Ctx:
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
    return Ctx(me=me, emps=emps, hr_scope=scope, line=line, private=set(private or ()) - {me.get("companyId")})


# ---------------------------------------------------------------- reading
def _isolate(st: dict, ctx: Ctx):
    """Each registered company sees only itself. Only the group administrator (the platform company) sees all.
    A record belongs to its companyId, or to the company of the employee it is about."""
    from .collections import COLLS
    emp_co = {e["id"]: e.get("companyId") for e in st.get("employees", [])}
    if ctx.is_super:
        mine = {c.get("id") for c in st.get("companies", [])} - ctx.private
    else:
        mine = {ctx.me.get("companyId"), *(ctx.hr_scope or set())} - {None}
    req_co = {r.get("id"): r.get("companyId") for r in st.get("reqs", [])}
    app_co = {a.get("id"): a.get("companyId") or req_co.get(a.get("reqId")) for a in st.get("apps", [])}
    cand_co: dict = {}
    for a in st.get("apps", []):
        if a.get("candId"):
            cand_co.setdefault(a["candId"], set()).add(app_co.get(a.get("id")))

    def owner(coll, x):
        if coll == "companies":
            return x.get("id")
        if x.get("companyId"):
            return x["companyId"]
        for k in ("empId", "to", "from", "by", "createdBy"):
            if x.get(k) in emp_co:
                return emp_co[x[k]]
        if coll == "apps":
            return req_co.get(x.get("reqId"))
        if coll == "interviews":
            return app_co.get(x.get("appId"))
        return None

    for c in COLLS:
        if c.name == "cands":
            st[c.name] = [x for x in st.get(c.name, []) if owner(c.name, x) in mine or (cand_co.get(x.get("id"), set()) & mine)]
        else:
            st[c.name] = [x for x in st.get(c.name, []) if owner(c.name, x) in mine]
    st["roster"] = {k: v for k, v in (st.get("roster") or {}).items() if emp_co.get(k) in mine}
    st["audit"] = [a for a in st.get("audit", []) if emp_co.get(a.get("by")) in mine]


def redact_state(conn, st: dict, ctx: Ctx) -> dict:
    if ctx.is_super:
        if ctx.private:
            _isolate(st, ctx)
        for e in st["employees"]:
            security_fields.mask_employee(conn, e)
        return st
    _isolate(st, ctx)
    emp_co = {e["id"]: e.get("companyId") for e in st["employees"]}
    sees_all = lambda emp_id: emp_id == ctx.id or ctx.is_hr_for(emp_co.get(emp_id))  # noqa: E731

    fin = lambda co: ctx.is_finance_for(co)  # noqa: E731
    for e in st["employees"]:
        if e["id"] == ctx.id and not ctx.is_hr_for(e.get("companyId")):
            workforce.redact_employee(e, "self")
        elif not sees_all(e["id"]):
            workforce.redact_employee(e, "line" if e["id"] in ctx.line else "other")
            pay = fin(e.get("companyId"))           # finance keeps what payroll needs
            for k, blank in SENSITIVE_EMP.items():
                if k in e and not (pay and k in FINANCE_SEES):
                    e[k] = blank
            if not pay and isinstance(e.get("dob"), str) and len(e["dob"]) == 10:
                e["dob"] = "1900" + e["dob"][4:]          # keeps birthdays on the home page, hides age
            for s in e.get("stints") or []:
                if not pay:
                    s.pop("ctc", None)
        # Masking-with-reveal sits on top of the access control above: whatever real value
        # survived for this viewer (self/HR/finance/coworker) is masked by default here, never
        # un-redacted further -- see security_fields.mask_employee.
        security_fields.mask_employee(conn, e)
    for run in st["payRuns"]:
        if not ctx.is_hr_for(run.get("companyId")) and not fin(run.get("companyId")):
            run["results"] = {k: v for k, v in (run.get("results") or {}).items() if k == ctx.id}
            run["skipped"] = []
            run["bills"], run["payments"] = {}, []        # what is owed and paid to contractors is for HR
    st["payInputs"] = [x for x in st["payInputs"] if fin(x.get("companyId")) or (sees_all(x.get("empId")) and (x.get("empId") == ctx.id or ctx.is_hr_for(x.get("companyId"))))]
    st["declarations"] = [x for x in st["declarations"] if sees_all(x.get("empId")) or fin(emp_co.get(x.get("empId")))]
    st["leaveAdj"] = [x for x in st["leaveAdj"] if x.get("empId") == ctx.id or x.get("empId") in ctx.line or ctx.is_hr_for(emp_co.get(x.get("empId")))]
    st["audit"] = [a for a in st["audit"] if ctx.is_hr_for(emp_co.get(a.get("by")))] if ctx.is_hr else []
    type_team = {t.get("id"): t.get("team") for t in st.get("assetTypes", [])}
    type_team_by_name = {(t.get("companyId"), str(t.get("name") or "").strip().lower()): t.get("team") for t in st.get("assetTypes", [])}

    def team_sees(coll, x):
        co = x.get("companyId") or emp_co.get(x.get("empId"))
        if coll == "expenseClaims":
            return fin(co) and x.get("status") != "draft"
        if coll == "assets":
            team = type_team.get(x.get("typeId")) or type_team_by_name.get((co, str(x.get("type") or "").strip().lower()))
            return bool(team) and ctx.in_team(team, co)
        return False
    for coll in PARTICIPANT:
        st[coll] = [x for x in st.get(coll, []) if ctx.is_hr_for(x.get("companyId") or emp_co.get(x.get("empId")))
                    or ctx.id in (x.get("participants") or []) or x.get("empId") == ctx.id or team_sees(coll, x)]
    comp.visible(st, ctx)
    training.visible(st, ctx)
    perf.visible(st, ctx)
    st["cands"] = [x if ctx.is_hr_for(x.get("companyId")) else candform.redact(x) for x in st.get("cands", [])]
    # 2.15: reimbursement runs are Finance's and HR's; employees see the run number on their claims
    st["reimbRuns"] = [x for x in st.get("reimbRuns", []) if ctx.is_hr_for(x.get("companyId")) or fin(x.get("companyId"))]
    hr_cos = {c.get("id") for c in st.get("companies", []) if ctx.is_hr_for(c.get("id"))}
    st["masterItems"] = [x for x in st.get("masterItems", []) if x.get("companyId") in hr_cos] + \
        workforce.visible_masters([x for x in st.get("masterItems", []) if x.get("companyId") not in hr_cos], ctx.id)
    st["contractors"] = [x if x.get("companyId") in hr_cos else
                         {k: v for k, v in x.items() if k != "portalUsers"} if fin(x.get("companyId")) else     # bills need the charges
                         {k: x.get(k) for k in ("id", "companyId", "name", "code")} for x in st.get("contractors", [])]
    if ctx.is_contract_worker:
        _contract_worker_view(st, ctx)
    if not ctx.is_hr:
        st["docTemplates"] = []          # only HR makes documents; employees see the finished letters on their profile
    s = st.get("settings") or {}
    st["settings"] = s if ctx.is_hr else {k: s.get(k) for k in ("googleClientId", "allowDemo", "allowPassword", "idleMin") if k in s}
    return st


def asset_team(conn, rec: dict | None):
    """The team (it or admin) that issues an asset, from its kind."""
    if not rec:
        return None
    if rec.get("typeId"):
        t = repo.get_records(conn, "assetTypes", [rec["typeId"]]).get(rec["typeId"])
        if t:
            return t.get("team")
    name = str(rec.get("type") or "").strip().lower()
    if name and rec.get("companyId"):
        for t in repo.records_where(conn, "assetTypes", "company_id", rec["companyId"]):
            if str(t.get("name") or "").strip().lower() == name:
                return t.get("team")
    return None


def _team_write(conn, coll: str, new: dict, old: dict | None, ctx: Ctx, co_new, co_old):
    """A change a team member (not HR) may make for their team. Returns the record, None when the team rules do not
    apply (the usual rules follow), or raises Rejected."""
    if not ctx.teams:
        return None
    if co_old is not None and co_new != co_old:
        return None
    if coll == "assetTypes":
        teams = {new.get("team"), (old or {}).get("team")} - {None}
        if not teams <= ASSET_TEAMS:
            raise Rejected("a kind of asset belongs to IT or Administration")
        if all(ctx.in_team(t, co_new) for t in teams):
            return new
        raise Rejected("only that team or HR keeps this list")
    if coll == "assets":
        teams = {asset_team(conn, new), asset_team(conn, old)} - {None}
        if teams and all(ctx.in_team(t, co_new) for t in teams if t in ASSET_TEAMS):
            if not new.get("typeId") and not new.get("type"):
                raise Rejected("say what kind of asset this is")
            return new
        return None                        # legacy assets and employees confirming receipt: the participant rules
    if not ctx.is_finance_for(co_new):
        return None
    if coll in FINANCE_WRITE:
        return new
    if coll == "payComps":
        if old:
            raise Rejected("pay components are set up by HR")
        return new                         # payroll and reimbursements add a missing component (e.g. 1900)
    if coll == "expenseClaims":
        subject = new.get("empId") or (old or {}).get("empId")
        if subject == ctx.id:
            return None                    # one's own claim: the usual rules (nobody approves their own)
        if old and old.get("status") == "draft" and new.get("status") == "draft":
            raise Rejected("a draft belongs to the person writing it")
        return new
    return None


def _contract_worker_view(st: dict, ctx: Ctx):
    for run in st.get("payRuns", []):
        run["results"] = {}                       # no payslips
    st["payInputs"], st["declarations"] = [], []
    st["expenseClaims"] = [x for x in st.get("expenseClaims", []) if x.get("empId") != ctx.id]
    st["requests"] = [x for x in st.get("requests", []) if not (x.get("empId") == ctx.id and x.get("kind") in CW_NO_REQUEST)]
    for e in st.get("employees", []):
        if e.get("id") == ctx.id:
            e.update({k: (v.copy() if hasattr(v, "copy") else v) for k, v in CW_HIDDEN_SELF.items()})
            for s in e.get("stints") or []:
                s.pop("ctc", None)


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


CODED = {"depts": "departments", "desigs": "designations", "grades": "grades", "locations": "locations"}


def check_upsert(conn, coll: str, new: dict, old: dict | None, ctx: Ctx) -> dict:
    """Returns the record to store, or raises Rejected."""
    if coll == "employees":
        # one e-mail address, one kind of sign-in: an address that already signs in as a candidate of another
        # company cannot become an employee's (its own company's candidate who joins keeps it: that is the hire)
        em = str(new.get("email") or "").strip().lower()
        if em and em != str((old or {}).get("email") or "").strip().lower():
            if candform.signin_companies(conn, em) - {new.get("companyId")}:
                raise Rejected("that e-mail address is already used for another sign-in. Use a different address")
    co_new, co_old = record_company(conn, coll, new, ctx), record_company(conn, coll, old, ctx)
    if coll in CODED and str(new.get("code") or "").strip():
        # two departments, designations, grades or locations of one company never share a code (checked here too,
        # not only on the screen)
        from sqlalchemy import text as _t
        clash = conn.execute(_t(f"SELECT JSON_UNQUOTE(JSON_EXTRACT(data, '$.name')) FROM {CODED[coll]} WHERE company_id=:c AND id<>:i "
                                "AND UPPER(TRIM(JSON_UNQUOTE(JSON_EXTRACT(data, '$.code'))))=:k LIMIT 1"),
                             {"c": new.get("companyId") or co_new, "i": new.get("id"), "k": str(new["code"]).strip().upper()}).scalar()
        if clash:
            raise Rejected(f"{clash} already has the code {str(new['code']).strip()}")
    if coll == "cands":
        # what the candidate entered through their link is kept as stored (candform.py)
        try:
            new = candform.merge_from_app(dict(new), old, ctx.id)
            new = cportal.merge_cand(new, old)       # 2.19: the conversation is written only on the server
        except candform.Problem as e:
            raise Rejected(str(e)) from None
    if coll == "apps":
        new = cportal.merge_app(dict(new), old)       # 2.19: what the candidate did in the portal stands
    if coll in ("apps", "interviews"):
        # 2.18: management approval, feedback, final selection and the signed offer (recruit.py), for everyone
        _recruit(conn, coll, new, old, ctx, co_new or co_old)
    if ctx.is_super:
        if ctx.private and ({co_new, co_old} & ctx.private or (coll == "employees" and set(new.get("hrCompanies") or []) & ctx.private)):
            raise Rejected("this belongs to another company")
        return new
    if old and co_old is None and coll != "companies":
        raise Rejected("this record belongs to another company")
    if co_new is None and coll != "companies":
        # a record that names no company belongs to the writer's company, so other companies never see it
        new = {**new, "companyId": ctx.me.get("companyId")}
        co_new = new["companyId"]
    hr_ok = all(c is None or ctx.is_hr_for(c) for c in (co_new, co_old)) and ctx.is_hr

    if coll == "employees":
        _check_photo(conn, new, old, ctx, hr_ok)
        return _employee(new, old, ctx, hr_ok)

    if hr_ok:
        return new
    team_ok = _team_write(conn, coll, new, old, ctx, co_new, co_old)
    if team_ok is not None:
        return team_ok
    if ctx.is_contract_worker:
        if coll in CW_NO_WRITE:
            raise Rejected("contract workers do not handle expense claims or tax declarations here: ask your contractor")
        if coll == "requests" and (new.get("kind") or (old or {}).get("kind")) in CW_NO_REQUEST:
            raise Rejected("contract workers do not encash leave here: ask your contractor")
    if coll in COMP:
        return _comp(conn, coll, new, old, ctx)
    if coll in TRAIN:
        return _train(conn, coll, new, old, ctx)
    if coll in PERF:
        if any(c not in (None, ctx.me.get("companyId")) for c in (co_new, co_old)):
            raise Rejected("belongs to another company")
        try:
            if coll == "perfMeetings":
                return perf.check_meeting(new, old, ctx.id, ctx.line)
            return perf.check_plan(new, old, ctx.id, ctx.line)
        except perf.Problem as e:
            raise Rejected(str(e)) from None
    if coll in PARTICIPANT:
        return _participant(conn, coll, new, old, ctx)
    if coll == "masterItems":
        if co_new != ctx.me.get("companyId"):
            raise Rejected("belongs to another company")
        try:
            return workforce.check_master(new, old, ctx.id)
        except workforce.Problem as e:
            raise Rejected(str(e)) from None
    if coll in HR_ONLY or coll not in WORKFLOW:
        raise Rejected("only HR can change this")
    own_co = ctx.me.get("companyId")
    if any(c not in (None, own_co) for c in (co_new, co_old)):
        raise Rejected("belongs to another company")

    subject = new.get("empId") or (old or {}).get("empId")
    if coll in ("leaveReqs", "regs") and old and old.get("steps") and subject != ctx.id and subject not in ctx.line:
        return _step_decision(new, old, ctx)
    if coll in ("leaveReqs", "regs") and not old and any((x or {}).get("decision") for x in new.get("steps") or []):
        raise Rejected("a new request cannot already be approved")
    if coll == "punches" and subject == ctx.id:
        _own_punch(new, old)
    if coll == "exits" and old and (new.get("stat") != old.get("stat") or new.get("fnf") != old.get("fnf")):
        raise Rejected("only HR records the PF and ESI exit and the settlement")
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


def _one(conn, coll: str, rid):
    return (repo.get_records(conn, coll, [rid]) or {}).get(rid) if rid else None


def _same_company(conn, ids: list, coid, ctx: Ctx):
    """Approvers, panel members and people referred to must be able to act for the requisition's company: they
    are e-mailed the candidate's details. The group administrator only for the companies of its own group."""
    private = repo.registered_companies(conn)
    for i in ids:
        if not i:
            continue
        e = ctx.emps.get(i) or {}
        if not (e.get("companyId") == coid or coid in (e.get("hrCompanies") or []) or (e.get("role") == "super" and coid not in private)):
            raise Rejected("approvers, interviewers and people referred to must be from this company")


def _recruit(conn, coll: str, new: dict, old: dict | None, ctx: Ctx, co):
    """2.18: an application or interview, against its requisition and the company's recruitment settings.
    Records saved earlier in the same batch are already in the database (companies, then requisitions,
    candidates, applications, then interviews)."""
    try:
        if coll == "apps":
            req = _one(conn, "reqs", new.get("reqId") or (old or {}).get("reqId"))
            coid = (req or {}).get("companyId") or co
            recruit.check_app(new, old, ctx.id, ctx.is_hr_for(coid), req, _one(conn, "companies", coid))
            _same_company(conn, [x.get("id") for x in ((new.get("shortlist") or {}).get("approvers") or []) if isinstance(x, dict)], coid, ctx)
            return
        app = _one(conn, "apps", new.get("appId") or (old or {}).get("appId"))
        req = _one(conn, "reqs", (app or {}).get("reqId"))
        coid = (req or {}).get("companyId") or co
        owners = {(req or {}).get("hiringMgr"), (req or {}).get("createdBy"), (old or {}).get("createdBy")} - {None, ""}
        recruit.check_interview(new, old, ctx.id, ctx.is_hr_for(coid), owners)
        _same_company(conn, list(new.get("panel") or []) + [x.get("to") for x in (new.get("referrals") or []) if isinstance(x, dict)], coid, ctx)
        if not old:
            recruit.check_new_interview(app, _one(conn, "companies", coid))
    except recruit.Problem as e:
        raise Rejected(str(e)) from None


def _comp_context(conn, rec: dict):
    cyc_id = rec.get("cycleId")
    cycle = (repo.get_records(conn, "compCycles", [cyc_id]) or {}).get(cyc_id) if cyc_id else None
    pools = repo.records_where(conn, "compBudgets", "cycle_id", cyc_id) if cyc_id else []
    return cycle, pools


def _comp(conn, coll: str, new: dict, old: dict | None, ctx: Ctx) -> dict:
    """Budgets and salary recommendations changed by a manager (HR is allowed everything above)."""
    if old and new.get("cycleId") != old.get("cycleId"):
        raise Rejected("a budget or recommendation cannot move to another cycle")
    cycle, pools = _comp_context(conn, old or new)
    if cycle and cycle.get("companyId") != ctx.me.get("companyId"):
        raise Rejected("belongs to another company")
    if (new.get("companyId") or (cycle or {}).get("companyId")) != (cycle or {}).get("companyId"):
        raise Rejected("belongs to another company")
    try:
        if coll == "compBudgets":
            return comp.check_pool(new, old, ctx.id, ctx.line, ctx.emps, cycle, pools)
        return comp.check_rec(new, old, ctx.id, ctx.emps, cycle, pools)
    except comp.Problem as e:
        raise Rejected(str(e)) from None


def _train(conn, coll: str, new: dict, old: dict | None, ctx: Ctx) -> dict:
    """Trainings, enrolments and feedback changed by someone who is not HR for the company."""
    try:
        if coll == "trainings":
            return training.check_training(new, old, ctx.id)
        tid = (old or new).get("trainingId")
        tr = (repo.get_records(conn, "trainings", [tid]) or {}).get(tid) if tid else None
        enrols = repo.records_where(conn, "trainingEnrols", "training_id", tid) if tid else []
        if coll == "trainingEnrols":
            return training.check_enrol(new, old, ctx.id, ctx.line, tr, enrols, ctx.emps)
        return training.check_feedback(new, old, ctx.id, tr, enrols, repo.records_where(conn, "trainingFeedback", "training_id", tid) if tid else [])
    except training.Problem as e:
        raise Rejected(str(e)) from None


def check_comp_budgets(conn, cycle_ids, ctx: Ctx):
    """After a save: no budget in the cycles touched hands down or (once finished) spends more than it has."""
    for cyc_id in {c for c in cycle_ids if c}:
        cycle = (repo.get_records(conn, "compCycles", [cyc_id]) or {}).get(cyc_id)
        if not cycle:
            continue
        pools = repo.records_where(conn, "compBudgets", "cycle_id", cyc_id)
        recs = repo.records_where(conn, "compRecs", "cycle_id", cyc_id)
        try:
            comp.check_budgets(cycle, pools, recs, ctx.emps)
        except comp.Problem as e:
            raise Rejected(str(e)) from None


def _own_punch(new: dict, old: dict | None):
    """Employees punch in and out for today, at the time they do it. Any other change to their punches
    is an attendance correction, which goes for approval."""
    import time as _t
    from datetime import date as _d
    from datetime import timedelta as _td
    # today, or yesterday for a night shift punched out after midnight
    if new.get("date") not in (_d.today().isoformat(), (_d.today() - _td(days=1)).isoformat()):
        raise Rejected("punch times can only be changed through an attendance correction")
    now = _t.time() * 1000
    for k in ("in", "out"):
        v, was = new.get(k), (old or {}).get(k)
        if v != was and v is not None and abs(float(v) - now) > 15 * 60 * 1000:
            raise Rejected("punch times can only be changed through an attendance correction")
        if was is not None and v is None:
            raise Rejected("punch times can only be changed through an attendance correction")


def _step_decision(new: dict, old: dict, ctx: Ctx) -> dict:
    """A workflow approver outside the reporting line (dotted-line manager, head of department, a named
    person) may record their own step's decision on a leave request, and nothing else."""
    steps_old, steps_new = old.get("steps") or [], new.get("steps") or []
    if len(steps_old) != len(steps_new) or not any(ctx.id in (x or {}).get("approverIds", []) for x in steps_old):
        raise Rejected("not in your reporting line")
    allowed = {"steps", "status", "decidedBy", "decidedAt", "note", "log"}
    for k in set(new) | set(old):
        if k not in allowed and new.get(k) != old.get(k):
            raise Rejected("an approver can only record a decision")
    for o, n in zip(steps_old, steps_new):
        if (n or {}).get("approverIds") != (o or {}).get("approverIds"):
            raise Rejected("the approvers cannot be changed")
        if (n or {}).get("decision") != (o or {}).get("decision") and (o.get("decision") or ctx.id not in (o.get("approverIds") or [])):
            raise Rejected("this step is not yours to decide")
    if new.get("status") == "approved" and not all((x or {}).get("decision") == "approved" for x in steps_new):
        raise Rejected("every step must be approved first")
    return new


def _participant(conn, coll: str, new: dict, old: dict | None, ctx: Ctx) -> dict:
    """Approval requests, expense claims, onboarding and assets for people who are not HR:
    only those taking part may change them, an approval step can only be decided by its approver,
    nobody approves their own request, and only HR finishes (applies, pays, completes) one."""
    own_co = ctx.me.get("companyId")
    if (new.get("companyId") or own_co) != own_co:
        raise Rejected("belongs to another company")
    if not old:
        if coll in ("requests", "expenseClaims"):
            # who approves this, and in what order, is resolved here from the company's own
            # approval-workflow settings -- never trusted from the client (workflow.py)
            steps, participants = workflow.build_steps_for(conn, ctx.emps, coll, new, ctx.id)
            new = {**new, "steps": steps, "participants": participants}
        if ctx.id not in (new.get("participants") or []):
            raise Rejected("you are not taking part in this")
        subject = new.get("empId")
        if coll != "assets" and subject and subject != ctx.id and subject not in ctx.line:
            raise Rejected("not in your reporting line")
        if any((s or {}).get("decision") for s in new.get("steps") or []) or new.get("status") in FINAL_STATUSES:
            raise Rejected("a new request cannot already be approved")
        return new
    if ctx.id not in (old.get("participants") or []):
        raise Rejected("you are not taking part in this")
    merged = dict(new)
    merged["participants"] = old.get("participants") or []        # the people involved are fixed when it starts
    old_steps, new_steps = old.get("steps") or [], new.get("steps") or []
    if len(new_steps) != len(old_steps) and old.get("status") not in (None, "draft"):
        raise Rejected("the approval steps cannot be changed")
    decided_now = []
    for i, ns in enumerate(new_steps):
        os_ = old_steps[i] if i < len(old_steps) else {}
        if os_ and (ns.get("approverIds") or []) != (os_.get("approverIds") or []) and old.get("status") not in (None, "draft"):
            raise Rejected("the approvers cannot be changed")
        if ns.get("decision") != os_.get("decision"):
            if os_.get("decision") or ctx.id not in (os_.get("approverIds") or []) or ctx.id == old.get("empId"):
                raise Rejected("this step is not yours to decide")
            decided_now.append(i)
    if new.get("status") != old.get("status") and new.get("status") in FINAL_STATUSES:
        all_ok = new_steps and all((x or {}).get("decision") == "approved" for x in new_steps)
        if not (new.get("status") == "approved" and all_ok and decided_now) and coll not in ("onboardings", "assets"):
            raise Rejected("only HR can finish this")
        if coll == "onboardings" and new.get("status") == "completed":
            raise Rejected("only HR can complete onboarding")
    if coll == "onboardings":
        old_tasks = {t.get("id"): t for t in old.get("tasks") or []}
        for t in new.get("tasks") or []:
            ot = old_tasks.get(t.get("id"))
            if ot is None:
                raise Rejected("only HR can add onboarding tasks")
            if {k: v for k, v in t.items() if k != "log"} != {k: v for k, v in ot.items() if k != "log"} and ctx.id not in (ot.get("ownerIds") or []):
                raise Rejected("that task belongs to another department")
    return merged


def _check_photo(conn, new: dict, old: dict | None, ctx: Ctx, hr_ok: bool):
    """2.15: a profile photo is seen by everyone in the company, so it must be an image uploaded by the person setting
    it (or by HR), never another file the writer happens to know the id of."""
    pid = new.get("photoId")
    if not pid or pid == (old or {}).get("photoId"):
        return
    if not isinstance(pid, str) or len(pid) > 64:
        raise Rejected("that photo cannot be used")
    row = conn.execute(text("SELECT mime, owner_emp FROM files WHERE id=:i"), {"i": pid}).fetchone()
    if not row or not str(row.mime or "").startswith("image/"):
        raise Rejected("the photo must be an image")
    if row.owner_emp != ctx.id and not hr_ok:
        raise Rejected("upload the photo yourself")


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
        for k in PROTECTED_SELF | (set(CW_HIDDEN_SELF) if ctx.is_contract_worker else set()):
            if k in old:
                merged[k] = old[k]
            else:
                merged.pop(k, None)
        try:
            return workforce.keep_verification(merged, old)
        except workforce.Problem as e:
            raise Rejected(str(e)) from None
    if ctx.is_finance_for(old.get("companyId")) and new["id"] not in ctx.line:
        # finance works from a copy without the person's private details: only the tax regime is taken from it
        if any(k in new and new.get(k) != old.get(k) for k in FINANCE_MAY):
            return {**old, **{k: new[k] for k in FINANCE_MAY if k in new}}
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
    co = record_company(conn, coll, old, ctx)
    if ctx.is_super:
        if co in ctx.private:
            raise Rejected("this belongs to another company")
        return
    if co is None and coll != "companies":
        raise Rejected("this record belongs to another company")
    if ctx.is_hr and ctx.is_hr_for(co):
        if coll == "employees" and old.get("role") == "super":
            raise Rejected("only the group administrator can remove a group administrator")
        return
    if coll in ("requests", "expenseClaims") and old.get("empId") == ctx.id and old.get("status") in ("draft", "withdrawn", None):
        return
    if coll in ("payRuns", "payInputs") and ctx.is_finance_for(co):
        return
    if coll == "assetTypes" and old.get("team") in ASSET_TEAMS and ctx.in_team(old["team"], co):
        return
    if coll == "compBudgets":
        cycle, pools = _comp_context(conn, old)
        try:
            comp.check_pool_delete(old, ctx.id, cycle, pools)
        except comp.Problem as e:
            raise Rejected(str(e)) from None
        return
    if coll == "compRecs":
        raise Rejected("only HR can take someone out of a salary plan")
    if coll in PERF:
        if co == ctx.me.get("companyId") and perf.may_delete(coll, old, ctx.id, ctx.line):
            return
        raise Rejected("not yours to delete")
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
    # group name, sign-in settings and statutory rates are shared by every company: only the group administrator
    if not ctx.is_super:
        raise Rejected("only the group administrator can change these settings")


def check_roster(emp_id: str, ctx: Ctx):
    e = ctx.emps.get(emp_id)
    if (e and ctx.is_hr_for(e.get("companyId"))) or emp_id in ctx.line:
        return
    raise Rejected("you can only roster your own team")
