"""2.18: the recruitment flow, checked on the server.

    CVs (job portal import or the candidate's form)
      -> HR shortlists (Screening)
      -> management approves the shortlist (stage "approval", record app.shortlist)
      -> interviews; each panel member fills in the feedback form: hire, reject, hold or refer to others
         (people referred to give their own decision: interview.referrals)
      -> final selection: HR proposes, the hiring manager decides (app.sel)
      -> offer rounds; the offer is accepted only with the signed copy (app.offer.signed)
      -> joining (existing 2.14 closure) and the employee record

The company's settings are on the company record, `rflow` (see flow()). Pure functions: policy.py looks
up the records and calls these. Each raises Problem with the reason shown to the person.
"""

class Problem(Exception):
    pass


PRE_IV = {"sourced", "screening", "approval"}                         # before management approval
POST_IV = {"interview", "selected", "offer", "offered", "accepted", "joined"}
PRE_SEL = PRE_IV | {"interview"}                                      # before the final selection
POST_SEL = {"selected", "offer", "offered", "accepted", "joined"}
SL_DECISIONS = {"approve", "reject", "hold"}
SEL_DECISIONS = {"select", "reject", "hold"}
RECS = {"hire", "reject", "hold", "refer", "strong", "no"}            # strong and no: feedback before 2.18
REF_DECISIONS = {"hire", "reject", "hold"}

FLOW_DEFAULTS = {"slOn": True, "slHM": True, "slIds": [], "slRule": "any", "selOn": True, "signOn": True}


def flow(company: dict | None) -> dict:
    """The company's recruitment flow settings, with the standard values for anything not set."""
    return {**FLOW_DEFAULTS, **((company or {}).get("rflow") or {})}


def sl_status(sl: dict) -> str:
    """Where a shortlist approval stands, from the approvers' decisions and the rule.
    any: the first decision settles it (a hold can still be changed to approve or reject).
    all: a rejection by anyone rejects; approved when everyone approves; on hold when nobody is left to decide
    and someone holds."""
    apps = [x for x in (sl.get("approvers") or []) if isinstance(x, dict)]
    ds = [x.get("decision") or "" for x in apps]
    if not apps:
        return "pending"
    if (sl.get("rule") or "any") == "all":
        if "reject" in ds:
            return "rejected"
        if all(d == "approve" for d in ds):
            return "approved"
        if "" not in ds and "hold" in ds:
            return "hold"
        return "pending"
    # any: the latest decision counts (an approver may move a hold on)
    decided = sorted((x for x in apps if x.get("decision")), key=lambda x: x.get("at") or 0)
    if not decided:
        return "pending"
    return {"approve": "approved", "reject": "rejected", "hold": "hold"}[decided[-1]["decision"]]


def _same(a, b, keys) -> bool:
    return all((a or {}).get(k) == (b or {}).get(k) for k in keys)


# ---------------------------------------------------------------- applications
def check_app(new: dict, old: dict | None, me: str, is_hr: bool, req: dict | None, company: dict | None) -> None:
    """An application (one candidate on one requisition) written by `me`."""
    f = flow(company)
    req = req or {}
    owner = is_hr or me in {req.get("hiringMgr"), req.get("createdBy")}
    old = old or {}
    _check_shortlist(new.get("shortlist"), old.get("shortlist"), me, is_hr, owner)
    _check_selection(new.get("sel"), old.get("sel"), me, is_hr, owner, req)

    was, now = old.get("stage"), new.get("stage")
    if old and was != now:
        sl = new.get("shortlist") or {}
        if f["slOn"] and was in PRE_IV and now in POST_IV and sl.get("status") not in ("approved", "skipped"):
            raise Problem("management has not approved this candidate for interviews yet")
        sel = new.get("sel") or {}
        if f["selOn"] and was in PRE_SEL and now in POST_SEL and not (sel.get("status") == "decided" and sel.get("final") == "select"):
            raise Problem("the candidate is selected only through the final selection with the hiring manager")
        if not owner:
            # someone who is neither HR nor the requisition's owner moves a candidate only by deciding:
            # an approver on the shortlist, or the hiring manager on the final selection
            by_sl = was == "approval" and now in ("interview", "rejected") and (new.get("shortlist") or {}) != (old.get("shortlist") or {})
            by_sel = was == "interview" and now in ("selected", "rejected") and (new.get("sel") or {}) != (old.get("sel") or {})
            if not (by_sl or by_sel):
                raise Problem("only HR and the hiring manager move candidates from one stage to another")

    o_new, o_old = new.get("offer") or {}, old.get("offer") or {}
    if f["signOn"] and o_new.get("status") == "accepted" and o_old.get("status") != "accepted":
        sg = o_new.get("signed") or {}
        if not (sg.get("fileId") or (sg.get("esign") or {}).get("name")):
            raise Problem("attach the signed offer letter to record the acceptance")
    if (o_new.get("signed") or None) != (o_old.get("signed") or None) and not owner:
        raise Problem("only HR and the hiring manager record the signed offer letter")


def _check_shortlist(new, old, me, is_hr, owner):
    if new == old:
        return
    if not new:
        if not is_hr:
            raise Problem("only HR withdraws a shortlist from approval")
        return
    if not isinstance(new, dict):
        raise Problem("the shortlist approval is not readable")
    apps = new.get("approvers") or []
    fresh = not old or new.get("sentAt") != (old or {}).get("sentAt")
    if new.get("status") == "skipped":
        if not is_hr:
            raise Problem("only HR can take a candidate to interviews without management approval")
        if len(str(new.get("skipReason") or "").strip()) < 3:
            raise Problem("give the reason for interviewing without management approval")
        if not fresh and (old or {}).get("status") != "skipped" and any(x.get("decision") for x in apps):
            raise Problem("management has already decided on this candidate")
        return
    if fresh:
        if not owner:
            raise Problem("only HR and the hiring manager send a shortlist for approval")
        if new.get("by") != me:
            raise Problem("a shortlist is sent in your own name")
        if not apps:
            raise Problem("the shortlist needs at least one approver")
        if any(x.get("decision") for x in apps) or new.get("status") != "pending":
            raise Problem("a shortlist cannot be sent already decided")
        if (new.get("rule") or "any") not in ("any", "all"):
            raise Problem("unknown approval rule")
        return
    # the same shortlist: only decisions change, each by the approver concerned
    if not _same(new, old, ("by", "sentAt", "rule", "reqId")):
        raise Problem("a shortlist sent for approval cannot be changed; send it again instead")
    o_by = {x.get("id"): x for x in (old.get("approvers") or [])}
    if [x.get("id") for x in apps] != [x.get("id") for x in (old.get("approvers") or [])]:
        raise Problem("the approvers of a shortlist cannot be changed after it is sent")
    for x in apps:
        before = o_by.get(x.get("id")) or {}
        if not _same(x, before, ("decision", "note", "at")):
            if x.get("id") != me:
                raise Problem("each approver decides only for themselves")
            if x.get("decision") not in SL_DECISIONS:
                raise Problem("approve, reject or hold")
            if before.get("decision") in ("approve", "reject") and (old.get("status") in ("approved", "rejected")):
                raise Problem("this candidate has already been decided")
            if x.get("decision") in ("reject", "hold") and len(str(x.get("note") or "").strip()) < 3:
                raise Problem("give a reason for rejecting or holding a candidate")
    if new.get("status") != sl_status(new):
        raise Problem("the shortlist's status does not match the approvers' decisions")


def _check_selection(new, old, me, is_hr, owner, req):
    if new == old:
        return
    if not new:
        if not is_hr:
            raise Problem("only HR withdraws a final selection")
        return
    old = old or {}
    proposal = ("proposed", "rank", "note", "by", "at", "round", "mgrId")
    if not _same(new, old, proposal):
        if not owner:
            raise Problem("only HR and the hiring manager propose the final selection")
        if new.get("by") != me:
            raise Problem("a proposal is made in your own name")
        if new.get("proposed") not in SEL_DECISIONS:
            raise Problem("propose select, reject or hold")
        if (new.get("mgrId") or "") != (req.get("hiringMgr") or ""):
            raise Problem("the final selection goes to the requisition's hiring manager")
        if new.get("round") == old.get("round") and old.get("status") == "decided" and old:
            raise Problem("start a new round to change a decided selection")
    mgr, mgr_old = new.get("mgr") or None, old.get("mgr") or None
    if mgr != mgr_old and mgr:
        if new.get("mgrId"):
            if mgr.get("by") != me or me != new.get("mgrId"):
                raise Problem("only the hiring manager decides the final selection")
        elif not (is_hr and mgr.get("by") == me):
            raise Problem("without a hiring manager, HR decides the final selection")
        if mgr.get("decision") not in SEL_DECISIONS:
            raise Problem("select, reject or hold")
        if mgr.get("decision") != new.get("proposed") and len(str(mgr.get("note") or "").strip()) < 3:
            raise Problem("give a reason when you decide differently from HR's proposal")
    want_status = "decided" if mgr else "proposed"
    if new.get("status") != want_status:
        raise Problem("the final selection's status does not match the decision")
    if (new.get("final") or "") != ((mgr or {}).get("decision") or ""):
        raise Problem("the final selection must be the hiring manager's decision")


# ---------------------------------------------------------------- interviews
def check_interview(new: dict, old: dict | None, me: str, is_hr: bool, owners: set) -> None:
    """An interview written by `me`. owners: the requisition's hiring manager and creator, and whoever
    scheduled the interview. HR and owners change the interview; panel members give their own feedback;
    people referred to give their own decision."""
    owner = is_hr or me in owners
    old_ = old or {}
    if not old and not owner:
        raise Problem("only HR and the hiring manager schedule interviews")

    fb_new, fb_old = new.get("feedback") or {}, old_.get("feedback") or {}
    for who in set(fb_new) | set(fb_old):
        if fb_new.get(who) != fb_old.get(who):
            v = fb_new.get(who) or {}
            mine = who == me or (is_hr and v.get("enteredBy") == me and who in (new.get("panel") or []))
            if not mine:
                raise Problem("each panel member gives only their own feedback")
            if who in fb_new and v.get("rec") not in RECS:
                raise Problem("recommend hiring, rejection, hold or referral to others")
            if who in fb_new and v.get("rec") == "refer" and not v.get("referTo"):
                raise Problem("choose whom to refer the decision to")

    r_new = {x.get("id"): x for x in (new.get("referrals") or []) if isinstance(x, dict)}
    r_old = {x.get("id"): x for x in (old_.get("referrals") or []) if isinstance(x, dict)}
    for rid in set(r_new) | set(r_old):
        a, b = r_new.get(rid), r_old.get(rid)
        if a == b:
            continue
        if b is None:
            if a.get("by") != me:
                raise Problem("a referral is made in your own name")
            if a.get("decision"):
                raise Problem("a referral cannot be made already decided")
            if not a.get("to") or a.get("to") == me:
                raise Problem("refer the decision to someone else")
            continue
        if a is None:
            if not (is_hr or (b.get("by") == me and not b.get("decision"))):
                raise Problem("only HR removes a referral once it is answered")
            continue
        if not _same(a, b, ("to", "by", "at", "question")):
            raise Problem("a referral cannot be changed once made")
        if a.get("to") != me:
            raise Problem("only the person referred to gives this decision")
        if a.get("decision") not in REF_DECISIONS:
            raise Problem("recommend hiring, rejection or hold")

    if not owner:
        skip = {"feedback", "referrals", "status"}
        for k in set(new) | set(old_):
            if k not in skip and new.get(k) != old_.get(k):
                raise Problem("only HR and the hiring manager change an interview")
        if new.get("status") != old_.get("status") and not (old_.get("status") == "scheduled" and new.get("status") == "completed"):
            raise Problem("only HR and the hiring manager change an interview")


def check_new_interview(app: dict | None, company: dict | None) -> None:
    """A new interview: the candidate must have management's approval (when the company asks for it)."""
    if not app:
        return
    if flow(company)["slOn"] and app.get("stage") in PRE_IV and (app.get("shortlist") or {}).get("status") not in ("approved", "skipped"):
        raise Problem("management has not approved this candidate for interviews yet")
