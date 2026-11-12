"""
Approval workflow resolution.

Who approves a request, in what order, was decided entirely in the browser until now
(frontend/src/engine/engine.js: FLOW_TYPES, buildSteps(), participantsOf()) -- the server only
checked the *integrity* of whatever steps/approverIds the client submitted (policy.py), never who
they should have been. That let a raw API call fabricate any approverIds it liked.

This module is a server-side, faithful port of that same resolution, run instead of trusted: when a
request/expense claim/etc. is first created, policy.py calls build_steps_for() here and the client's
own steps/participants are discarded. Keep FLOW_TYPES/LEVELS here in step with engine.js's copies --
they describe the same thing on both sides so a company's "Approval workflows" settings page keeps
meaning what it always meant.

One level is new here, not yet editable from the legacy `VIEWS.flows` admin view: "group:<id>",
naming a reusable, named approverGroups record (a company can set this directly in a flow's step
JSON; the admin view will grow a picker for it as a follow-up).
"""
from . import repo

# unit: None for amount-of-money steps ("minAmount" is a plain number); "days" for leave (a day-count
# threshold compares with a strict "more than", matching engine.js's own amount/unit rule).
FLOW_TYPES = {
    "expense": {"hrLast": False, "unit": None},
    "encash": {"hrLast": True, "unit": None},
    "promotion": {"hrLast": True, "unit": None},
    "statutory": {"hrLast": True, "unit": None},
    "attendance": {"hrLast": False, "unit": None},
    "shiftchange": {"hrLast": False, "unit": None},
    "leave": {"hrLast": False, "unit": "days"},
}
DEFAULT_CHAIN = {
    "expense": [{"level": "manager"}, {"level": "finance"}],
    "encash": [{"level": "manager"}, {"level": "hr"}],
    "promotion": [{"level": "skip"}, {"level": "hr"}],
    "statutory": [{"level": "hr"}],
    "attendance": [{"level": "manager"}],
    "shiftchange": [{"level": "manager"}],
    "leave": [{"level": "manager"}],
}
LEVELS = {"manager": "Line manager", "matrix": "Dotted-line manager", "skip": "Manager’s manager",
          "deptHead": "Head of department", "payroll": "Payroll approver", "person": "A named person",
          "finance": "Finance team", "hr": "HR"}


def _active(e: dict | None) -> bool:
    return (e or {}).get("status") != "exited"


def _hr_ids_of(employees: dict, co_id, with_super: bool = True) -> list:
    """HR of the company; the group administrator too, except for a company that registered itself
    (those are private: the group administrator does not see or approve their requests)."""
    return [e["id"] for e in employees.values()
            if _active(e) and ((with_super and e.get("role") == "super") or (e.get("role") == "hr" and (e.get("companyId") == co_id or co_id in (e.get("hrCompanies") or []))))]


def _of_company(ids: list, employees: dict, co_id) -> list:
    """Only people who can act for this company: its own employees, its HR, the group administrator."""
    def ok(i):
        e = employees.get(i) or {}
        return e.get("companyId") == co_id or co_id in (e.get("hrCompanies") or []) or e.get("role") == "super"
    return [i for i in ids if i and ok(i)]


def _team_ids_of(employees: dict, co_id, team: str) -> list:
    return [e["id"] for e in employees.values() if e.get("companyId") == co_id and _active(e) and team in (e.get("teams") or [])]


def _step_applies(step: dict, data: dict | None) -> bool:
    """Expense-claim-only conditions: a step can be limited to certain purposes/categories, or to
    claims with an issue (over a limit, a missing receipt or document) -- see engine.js's stepApplies()."""
    if not data:
        return True
    purposes = step.get("purposes") or []
    if purposes and data.get("purposeId") not in purposes:
        return False
    cats = step.get("cats") or []
    if cats and not (set(data.get("catIds") or []) & set(cats)):
        return False
    if step.get("onIssues") and not data.get("issues"):
        return False
    return True


def flow_for(co: dict, kind: str) -> list:
    return (co.get("flows") or {}).get(kind) or DEFAULT_CHAIN.get(kind, [])


def _resolve_level(step: dict, emp: dict, employees: dict, depts: dict, co: dict, groups: dict) -> list:
    level = step.get("level")
    if level == "manager":
        return [emp.get("managerId")]
    if level == "matrix":
        return list(emp.get("matrixManagerIds") or [])
    if level == "skip":
        mgr = employees.get(emp.get("managerId")) or {}
        return [mgr.get("managerId")]
    if level == "deptHead":
        d = depts.get(emp.get("deptId")) or {}
        return [d.get("headId")]
    if level == "payroll":
        return [co.get("payrollApproverId")]
    sup = co.get("source") != "register"
    if level == "person":
        return _of_company([step.get("personId")], employees, emp.get("companyId")) if sup else [i for i in [step.get("personId")] if (employees.get(i) or {}).get("companyId") == emp.get("companyId")]
    if level == "hr":
        return _hr_ids_of(employees, emp.get("companyId"), sup)
    if level == "finance":
        f = _team_ids_of(employees, emp.get("companyId"), "finance")
        return f if f else _hr_ids_of(employees, emp.get("companyId"), sup)
    if level and level.startswith("group:"):
        ids = list((groups.get(level[6:]) or {}).get("employeeIds") or [])
        return _of_company(ids, employees, emp.get("companyId")) if sup else [i for i in ids if (employees.get(i) or {}).get("companyId") == emp.get("companyId")]
    return []


def build_steps(employees: dict, depts: dict, co: dict, groups: dict, kind: str, emp_id: str, requester_id: str, amount, data: dict | None) -> list:
    """Server-authoritative version of engine.js's buildSteps()."""
    emp = employees.get(emp_id) or {}
    ft = FLOW_TYPES.get(kind, {})
    unit = ft.get("unit")
    amt = float(amount or 0)

    def within(l):
        m = float(l.get("minAmount") or 0)
        if m <= 0:
            return True
        return amt > m if unit else amt >= m

    chain = [l for l in flow_for(co, kind) if within(l) and _step_applies(l, data)]
    if ft.get("hrLast") and (not chain or chain[-1].get("level") != "hr"):
        chain = [*chain, {"level": "hr"}]

    steps = []
    for l in chain:
        ids = list(dict.fromkeys(i for i in _resolve_level(l, emp, employees, depts, co, groups) if i))
        ids = [i for i in ids if i in employees and _active(employees[i]) and i != emp_id and (l.get("level") == "hr" or i != requester_id)]
        if not ids:
            continue      # nobody in that role: the step is skipped
        if steps and steps[-1]["approverIds"] == ids:
            continue      # same person(s) twice in a row approves once
        steps.append({"level": l.get("level"), "approverIds": ids, "decision": "", "by": "", "at": 0, "note": ""})
    return steps


def participants_of(rec: dict, employees: dict, with_super: bool = True) -> list:
    co_id = rec.get("companyId")
    out = [rec.get("empId"), rec.get("by")]
    for s in rec.get("steps") or []:
        out += s.get("approverIds") or []
    out += _hr_ids_of(employees, co_id, with_super)
    if rec.get("lines"):
        out += _team_ids_of(employees, co_id, "finance")
    return list(dict.fromkeys(i for i in out if i))


# map of collection name -> flow kind, and the amount/data this kind needs resolved from the record
KIND_OF_COLLECTION = {"expenseClaims": "expense"}      # "requests" carries its own kind in rec["kind"]


def _amount_and_data(coll: str, kind: str, rec: dict):
    if coll == "expenseClaims":
        return rec.get("total"), {"purposeId": rec.get("purposeId"), "catIds": [l.get("catId") for l in rec.get("lines") or [] if l.get("catId")],
                                   "issues": bool(rec.get("overLimit") or rec.get("missingDocs"))}
    if kind == "leave":
        return rec.get("days"), None
    return rec.get("amount"), None


def build_steps_for(conn, employees: dict, coll: str, rec: dict, requester_id: str) -> tuple[list, list]:
    """Looks up the company and its flow settings, resolves steps and participants for a new record
    about to be created in `coll` (requests or expenseClaims). Returns ([], []) if the kind has no
    flow (nothing to approve, e.g. onboardings/assets which use their own participants rule)."""
    kind = KIND_OF_COLLECTION.get(coll) or rec.get("kind")
    if kind not in FLOW_TYPES:
        return [], []
    emp_id = rec.get("empId")
    emp = employees.get(emp_id) or {}
    co_id = emp.get("companyId")
    cos = repo.get_records(conn, "companies", [co_id]) if co_id else {}
    co = cos.get(co_id) or {}
    depts = {d["id"]: d for d in repo.records_where(conn, "depts", "company_id", co_id)} if co_id else {}
    groups = {g["id"]: g for g in repo.records_where(conn, "approverGroups", "company_id", co_id)} if co_id else {}
    amount, data = _amount_and_data(coll, kind, rec)
    steps = build_steps(employees, depts, co, groups, kind, emp_id, requester_id, amount, data)
    participants = participants_of({**rec, "steps": steps}, employees, co.get("source") != "register")
    return steps, participants
