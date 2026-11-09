"""
PeopleDesk 2.11: performance records with their own rules (HR may do everything; these are the rules for others).

- Review meetings (perfMeetings, kind "review"): an employee and their manager meet about goals, a check-in or
  the appraisal, and the minutes and the actions agreed are recorded. The employee's managers (reporting line)
  arrange and record them. The people at the meeting and the employee see them; the employee may only add their
  acknowledgement (whether the minutes are a fair record, and a comment).
- Management meetings (perfMeetings, kind "management"): managers and HR discuss ratings and decide who is
  promoted, who is developed or put on an improvement plan, and who is asked to leave. Confidential: only HR and
  the people invited see them; the employees discussed do not (unless they were invited). The person who called
  the meeting or its chair records the minutes and the decisions. Outside HR a decision may only be about someone
  in the recorder's reporting line, and never about themselves.
- Succession plans (succession): a manager names possible successors for a position in their reporting line, or
  for their own, with readiness and development actions. Seen by HR, the plan's owner and the managers above the
  incumbent; not by the incumbent (unless they made it) and not by the successors named.
- Goals and reviews: the employee, their managers (line and dotted line) and HR see them; finance sees the final
  ratings, which variable pay is paid on.
"""

MEETING_KINDS = {"review", "management"}
EMP_MAY = {"empAck"}                 # what the employee changes on their own review meeting
IGNORED = {"log", "updatedAt", "updatedBy"}


class Problem(Exception):
    pass


def _changed(new: dict, old: dict) -> set:
    return {k for k in set(new) | set(old) if new.get(k) != old.get(k)} - IGNORED


# ---------------------------------------------------------------- who sees what
def sees_meeting(m: dict, me: str, line: set) -> bool:
    if m.get("kind") == "management":
        return me in (m.get("attendees") or []) or me in (m.get("createdBy"), m.get("chairId"))
    return me == m.get("empId") or me in (m.get("attendees") or []) or me == m.get("createdBy") or m.get("empId") in line


def sees_plan(p: dict, me: str, line: set) -> bool:
    return p.get("ownerId") == me or p.get("incumbentId") in line


def visible(st: dict, ctx) -> None:
    """Called for everyone who is not the group administrator (whose own company is already isolated)."""
    emp_co = {e["id"]: e.get("companyId") for e in st.get("employees", [])}
    dotted = {e["id"] for e in st.get("employees", []) if ctx.id in (e.get("matrixManagerIds") or [])}
    co_of = lambda x: x.get("companyId") or emp_co.get(x.get("empId"))  # noqa: E731
    st["perfMeetings"] = [m for m in st.get("perfMeetings", []) if ctx.is_hr_for(co_of(m)) or sees_meeting(m, ctx.id, ctx.line)]
    st["succession"] = [p for p in st.get("succession", []) if ctx.is_hr_for(co_of(p)) or sees_plan(p, ctx.id, ctx.line)]

    def mine(x):
        e = x.get("empId")
        return ctx.is_hr_for(co_of(x)) or e == ctx.id or e in ctx.line or e in dotted
    st["goals"] = [g for g in st.get("goals", []) if mine(g)]
    reviews = []
    for r in st.get("reviews", []):
        if mine(r):
            reviews.append(r)
        elif ctx.is_finance_for(co_of(r)):
            reviews.append({k: r.get(k) for k in ("id", "cycleId", "empId", "companyId", "final") if k in r})
    st["reviews"] = reviews


# ---------------------------------------------------------------- meetings
def check_meeting(new: dict, old: dict | None, me: str, line: set) -> dict:
    kind = (old or new).get("kind")
    if kind not in MEETING_KINDS or new.get("kind") != kind:
        raise Problem("a meeting is a review meeting or a management meeting, and stays one")
    if kind == "review":
        subject = (old or new).get("empId")
        if old and new.get("empId") != old.get("empId"):
            raise Problem("a review meeting stays with its employee")
        if subject in line:
            return new
        if subject == me and old:
            if _changed(new, old) - EMP_MAY:
                raise Problem("you can add your comments on the minutes; your manager records the meeting")
            return new
        raise Problem("only the employee's managers and HR record review meetings")
    # management meetings
    if old is None:
        if new.get("createdBy") != me:
            raise Problem("a management meeting is called in your own name")
    else:
        if me not in (old.get("createdBy"), old.get("chairId")):
            raise Problem("only the person who called the meeting or its chair records it")
        if new.get("createdBy") != old.get("createdBy"):
            raise Problem("who called the meeting cannot change")
    olds = {d.get("id"): d for d in (old or {}).get("decisions") or [] if isinstance(d, dict)}
    news = {d.get("id"): d for d in new.get("decisions") or [] if isinstance(d, dict)}
    for did, d in news.items():
        if olds.get(did) == d:
            continue
        _may_decide(d.get("empId"), me, line)
        if did in olds and olds[did].get("empId") != d.get("empId"):
            _may_decide(olds[did].get("empId"), me, line)
    for did, d in olds.items():
        if did not in news:
            _may_decide(d.get("empId"), me, line)
    return new


def _may_decide(emp_id, me: str, line: set):
    if emp_id == me:
        raise Problem("a decision about yourself is for your manager or HR")
    if emp_id not in line:
        raise Problem("outside HR, decisions may only be about people in your reporting line")


# ---------------------------------------------------------------- succession plans
def check_plan(new: dict, old: dict | None, me: str, line: set) -> dict:
    for inc in {new.get("incumbentId"), (old or {}).get("incumbentId")} - {None, ""}:
        if inc != me and inc not in line:
            raise Problem("succession plans are for positions in your reporting line, or your own")
    if old is None:
        if new.get("ownerId") != me:
            raise Problem("a succession plan is made in your own name")
    elif new.get("ownerId") != old.get("ownerId"):
        raise Problem("the plan's owner cannot change")
    if old is not None and old.get("ownerId") != me and old.get("incumbentId") not in line:
        raise Problem("this plan belongs to another manager")
    if new.get("incumbentId") == me and new.get("ownerId") != me:
        raise Problem("this plan belongs to another manager")
    was = (old or {}).get("hrReview")
    if new.get("hrReview") != was:
        raise Problem("only HR records its review of a plan")
    if new.get("status") == "reviewed" and (old or {}).get("status") != "reviewed":
        raise Problem("only HR marks a plan reviewed")
    if any((s or {}).get("empId") == new.get("incumbentId") for s in new.get("successors") or []):
        raise Problem("the person in the position cannot be their own successor")
    return new


def may_delete(coll: str, old: dict, me: str, line: set) -> bool:
    if coll == "perfMeetings":
        if old.get("kind") == "management":
            return me in (old.get("createdBy"), old.get("chairId")) and not any(
                (d or {}).get("empId") not in line for d in old.get("decisions") or [])
        return old.get("empId") in line
    if coll == "succession":
        return old.get("ownerId") == me and (old.get("incumbentId") == me or old.get("incumbentId") in line)
    return False
