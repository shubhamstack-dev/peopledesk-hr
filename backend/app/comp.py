"""
Compensation planning and salary revision: the rules the server enforces.

A cycle (compCycles) holds the organisation's increment budget, for example Rs 10,00,000, and the date the
new salaries take effect. HR hands budgets (compBudgets, "pools") to managers; each manager may hand part of
theirs to managers below them, and so on down the reporting line. Every eligible employee has one
recommendation (compRecs) with their current and proposed annual CTC.

Who decides an employee's increase: the nearest manager above them who holds a budget in the cycle. If nobody
above them holds one, HR decides from the organisation's budget. A budget therefore pays for

    the budgets handed to managers directly below it  +  the increases its holder decides

and may not be overspent. A budget is submitted when its holder has finished, then approved in turn by every
budget holder above them and finally by HR; any of them can send it back with comments. When every budget is
approved HR approves the cycle and applies it: the new salaries are written to the employees' salary history
from the effective date, so payroll picks them up in that month.

Employees serving notice or already gone are left out: their increase is not paid and does not use budget.
"""

EDITABLE = {"open", "returned"}
TOLERANCE = 1.0          # rupees, for rounding in the browser


class Problem(Exception):
    pass


def num(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def leaving(emp: dict | None) -> bool:
    return not emp or emp.get("status") in ("notice", "exited")


def counted(rec: dict, emps: dict) -> bool:
    """Whether a recommendation uses budget: not for people leaving, nor ones HR took out of the plan."""
    return not rec.get("excluded") and not leaving(emps.get(rec.get("empId")))


def hike(rec: dict) -> float:
    new, cur = num(rec.get("newCtc")), num(rec.get("currentCtc"))
    return max(0.0, new - cur) if new else 0.0


def pools_by_holder(pools) -> dict:
    return {p.get("empId"): p for p in pools if p.get("empId")}


def decider_pool(emp_id: str, emps: dict, by_holder: dict):
    """The budget that pays for this employee's increase: the nearest manager above them holding one.
    None means the organisation's budget (HR)."""
    seen = {emp_id}
    cur = (emps.get(emp_id) or {}).get("managerId")
    while cur and cur not in seen:
        if cur in by_holder:
            return by_holder[cur]
        seen.add(cur)
        cur = (emps.get(cur) or {}).get("managerId")
    return None


def ancestors(pool: dict, by_id: dict) -> list:
    """Budgets above this one, nearest first."""
    out, seen = [], {pool.get("id")}
    cur = by_id.get(pool.get("parentId"))
    while cur and cur.get("id") not in seen:
        out.append(cur)
        seen.add(cur.get("id"))
        cur = by_id.get(cur.get("parentId"))
    return out


def expected_steps(pool: dict, by_id: dict) -> list:
    """Approval chain for a submitted budget: every budget holder above, nearest first, then HR."""
    return [("mgr", [a.get("empId")]) for a in ancestors(pool, by_id)] + [("hr", [])]


def usage(pools, recs, emps) -> dict:
    """{pool id ('' for the organisation): {'allocated': handed down, 'spent': increases decided}}"""
    out = {"": {"allocated": 0.0, "spent": 0.0}}
    for p in pools:
        out.setdefault(p["id"], {"allocated": 0.0, "spent": 0.0})
    for p in pools:
        out.setdefault(p.get("parentId") or "", {"allocated": 0.0, "spent": 0.0})["allocated"] += num(p.get("amount"))
    by_holder = pools_by_holder(pools)
    for r in recs:
        if not counted(r, emps):
            continue
        d = decider_pool(r.get("empId"), emps, by_holder)
        out.setdefault(d["id"] if d else "", {"allocated": 0.0, "spent": 0.0})["spent"] += hike(r)
    return out


def rupees(v: float) -> str:
    v = round(v)
    s = str(abs(int(v)))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts) + "," + tail
    return ("-" if v < 0 else "") + "Rs " + s


def check_budgets(cycle: dict, pools: list, recs: list, emps: dict):
    """No budget may hand down more than it has, and a finished (submitted or approved) budget may not be
    overspent. The organisation's budget is checked the same way once the cycle is approved."""
    use = usage(pools, recs, emps)
    name = lambda p: f"{(emps.get(p.get('empId')) or {}).get('firstName', '')} {(emps.get(p.get('empId')) or {}).get('lastName', '')}".strip()  # noqa: E731
    total = num(cycle.get("budget"))
    root = use[""]
    if root["allocated"] > total + TOLERANCE:
        raise Problem(f"The budgets handed to managers ({rupees(root['allocated'])}) are more than the organisation's budget of {rupees(total)}")
    if cycle.get("status") in ("approved", "applied") and root["allocated"] + root["spent"] > total + TOLERANCE:
        raise Problem(f"The plan uses {rupees(root['allocated'] + root['spent'])}, more than the budget of {rupees(total)}")
    for p in pools:
        u, amt = use.get(p["id"], {"allocated": 0, "spent": 0}), num(p.get("amount"))
        if num(p.get("amount")) < 0:
            raise Problem("A budget cannot be negative")
        if u["allocated"] > amt + TOLERANCE:
            raise Problem(f"{name(p)} has handed down {rupees(u['allocated'])}, more than their budget of {rupees(amt)}")
        if p.get("status") not in EDITABLE and u["allocated"] + u["spent"] > amt + TOLERANCE:
            raise Problem(f"{name(p)}'s plan uses {rupees(u['allocated'] + u['spent'])}, more than their budget of {rupees(amt)}")


# ---------------------------------------------------------------- what someone who is not HR may change
POOL_FIXED = ("id", "cycleId", "companyId", "empId", "parentId", "chain")


def chain_of(parent: dict | None, by_id: dict) -> list:
    """Holders above a budget, nearest first. Kept on the budget so its holder, who cannot see the budgets
    above their own, knows who approves it."""
    if not parent:
        return []
    return [parent.get("empId")] + [a.get("empId") for a in ancestors(parent, by_id)]


def _changed(new: dict, old: dict) -> set:
    return {k for k in set(new) | set(old) if new.get(k) != old.get(k)}


def _comments_ok(new: dict, old: dict, me: str):
    oc, nc = old.get("comments") or [], new.get("comments") or []
    if len(nc) < len(oc) or nc[:len(oc)] != oc:
        raise Problem("comments cannot be changed or removed")
    if any((c or {}).get("by") != me for c in nc[len(oc):]):
        raise Problem("comments can only be written as yourself")


def check_pool(new: dict, old: dict | None, me: str, line: set, emps: dict, cycle: dict | None, pools: list):
    """A budget changed by a manager. pools: every budget of the cycle as saved now."""
    if not cycle or cycle.get("status") != "planning":
        raise Problem("salary planning is not open for this cycle")
    by_id = {p["id"]: p for p in pools}
    if old is None:
        parent = by_id.get(new.get("parentId"))
        if not parent or parent.get("cycleId") != new.get("cycleId") or parent.get("empId") != me:
            raise Problem("you can only hand down your own budget")
        if parent.get("status") not in EDITABLE:
            raise Problem("your budget is already submitted")
        if new.get("empId") not in line:
            raise Problem("not in your reporting line")
        if any(p.get("empId") == new.get("empId") for p in pools):
            raise Problem("that manager already has a budget in this cycle")
        others = [p for p in pools if p.get("id") != new.get("id")]
        d = decider_pool(new.get("empId"), emps, pools_by_holder(others))
        if not d or d.get("id") != parent.get("id"):
            raise Problem("a budget can only go to a manager whose nearest budget holder above is you")
        if list(new.get("chain") or []) != chain_of(parent, by_id):
            raise Problem("the approvers of a budget are the budget holders above it")
        if new.get("status") != "open" or any((s or {}).get("decision") for s in new.get("steps") or []) or new.get("comments"):
            raise Problem("a new budget starts open")
        if num(new.get("amount")) < 0:
            raise Problem("a budget cannot be negative")
        return new

    for k in POOL_FIXED:
        if new.get(k) != old.get(k):
            raise Problem("the budget holder and its place in the plan cannot be changed")
    changed = _changed(new, old) - {"comments", "log", "updatedAt"}
    _comments_ok(new, old, me)
    if not changed:
        return new
    parent = by_id.get(old.get("parentId"))
    is_parent = bool(parent) and parent.get("empId") == me
    is_holder = old.get("empId") == me
    steps_o, steps_n = old.get("steps") or [], new.get("steps") or []

    if changed == {"amount"}:
        if not is_parent:
            raise Problem("only the manager who handed down this budget can change it")
        if old.get("status") not in EDITABLE or parent.get("status") not in EDITABLE:
            raise Problem("the budget cannot change once submitted")
        return new

    if is_holder and old.get("status") in EDITABLE and new.get("status") == "submitted":
        if not changed <= {"status", "steps", "submittedAt", "submittedBy"}:
            raise Problem("submitting a budget cannot change anything else")
        want = expected_steps(old, by_id)
        got = [((s or {}).get("kind"), list((s or {}).get("approverIds") or [])) for s in steps_n]
        if got != want or any((s or {}).get("decision") for s in steps_n):
            raise Problem("the approvers of a budget are the managers above it and HR")
        return new

    if is_holder and old.get("status") == "submitted" and new.get("status") == "open":
        if any((s or {}).get("decision") == "approved" for s in steps_o):
            raise Problem("a budget can be taken back only before anyone has approved it")
        if not changed <= {"status", "steps", "submittedAt", "submittedBy"}:
            raise Problem("taking back a budget cannot change anything else")
        return new

    # an approver's decision on the current step
    i = next((n for n, s in enumerate(steps_o) if not (s or {}).get("decision")), None)
    if old.get("status") != "submitted" or i is None or len(steps_n) != len(steps_o):
        raise Problem("this budget is not waiting for a decision")
    s_o, s_n = steps_o[i] or {}, steps_n[i] or {}
    if s_o.get("kind") != "mgr" or me not in (s_o.get("approverIds") or []) or me == old.get("empId"):
        raise Problem("this step is not yours to decide")
    for n, (a, b) in enumerate(zip(steps_o, steps_n)):
        if n != i and a != b:
            raise Problem("only the current step can be decided")
    if {k for k in set(s_n) | set(s_o) if s_n.get(k) != s_o.get(k)} - {"decision", "by", "at", "note"}:
        raise Problem("the approvers cannot be changed")
    if s_n.get("decision") not in ("approved", "returned") or s_n.get("by") != me:
        raise Problem("record approve or send back, as yourself")
    if not changed <= {"steps", "status", "decidedAt"}:
        raise Problem("an approver can only record a decision and comments")
    last = i == len(steps_o) - 1
    want = "returned" if s_n["decision"] == "returned" else ("approved" if last else "submitted")
    if new.get("status") != want:
        raise Problem("the budget's status does not match the decision")
    return new


REC_MAY = {"newCtc", "note", "updatedAt", "updatedBy", "log"}


def check_rec(new: dict, old: dict | None, me: str, emps: dict, cycle: dict | None, pools: list):
    if old is None:
        raise Problem("only HR adds people to a salary plan")
    if not cycle or cycle.get("status") != "planning":
        raise Problem("salary planning is not open for this cycle")
    d = decider_pool(old.get("empId"), emps, pools_by_holder(pools))
    if not d or d.get("empId") != me or old.get("empId") == me:
        raise Problem("this person's increase is decided by someone else")
    if d.get("status") not in EDITABLE:
        raise Problem("your budget is already submitted; take it back to change it")
    if _changed(new, old) - REC_MAY:
        raise Problem("only the proposed salary and the note can be changed")
    if new.get("newCtc") not in (None, "") and num(new.get("newCtc")) < num(old.get("currentCtc")):
        raise Problem("the proposed salary is lower than the current one")
    return new


def check_pool_delete(old: dict, me: str, cycle: dict | None, pools: list):
    if not cycle or cycle.get("status") != "planning":
        raise Problem("salary planning is not open for this cycle")
    parent = next((p for p in pools if p.get("id") == old.get("parentId")), None)
    if not parent or parent.get("empId") != me:
        raise Problem("only the manager who handed down this budget can take it back")
    if old.get("status") not in EDITABLE or parent.get("status") not in EDITABLE:
        raise Problem("a submitted budget cannot be taken back")
    if any(p.get("parentId") == old.get("id") for p in pools):
        raise Problem("that manager has handed part of it down; they must take those back first")


# ---------------------------------------------------------------- reading
def visible(st: dict, ctx) -> None:
    """Budgets: HR, the holder and the managers above them. Recommendations: HR and the managers above the
    employee; never the employee themselves before the revision is announced. Cycles: those you take part in."""
    emp_co = {e["id"]: e.get("companyId") for e in st["employees"]}
    hr = lambda co: ctx.is_hr_for(co)  # noqa: E731
    st["compBudgets"] = [p for p in st.get("compBudgets", []) if hr(p.get("companyId")) or p.get("empId") == ctx.id or p.get("empId") in ctx.line]
    st["compRecs"] = [r for r in st.get("compRecs", []) if hr(r.get("companyId") or emp_co.get(r.get("empId")))
                      or (r.get("empId") in ctx.line and r.get("empId") != ctx.id)]
    mine = {p.get("cycleId") for p in st["compBudgets"]}
    out = []
    for c in st.get("compCycles", []):
        if hr(c.get("companyId")):
            out.append(c)
        elif c.get("id") in mine and c.get("status") != "draft":
            out.append({k: v for k, v in c.items() if k != "budget"})
    st["compCycles"] = out
