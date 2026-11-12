"""2.18: the recruitment flow rules (app/recruit.py). Pure functions, no database needed.
    cd backend && python -m pytest tests/test_recruit_flow.py -q
"""
import copy

import pytest

from app import recruit
from app.recruit import Problem

HR, HM, MGMT, PANEL, OTHER = "hr1", "hm1", "md1", "pn1", "x1"
REQ = {"id": "r1", "companyId": "co1", "hiringMgr": HM, "createdBy": HM}
CO = {"id": "co1"}                                  # standard settings: every step on


def app(stage="screening", **kw):
    return {"id": "a1", "reqId": "r1", "candId": "c1", "stage": stage, **kw}


def sent(rule="any", approvers=(HM, MGMT), by=HR, at=1):
    return {"status": "pending", "by": by, "sentAt": at, "rule": rule, "approvers": [{"id": i, "decision": ""} for i in approvers]}


def decide(sl, who, decision, note="", at=5):
    sl = copy.deepcopy(sl)
    for x in sl["approvers"]:
        if x["id"] == who:
            x.update(decision=decision, note=note, at=at)
    sl["status"] = recruit.sl_status(sl)
    return sl


# ---------------------------------------------------------------- shortlist approval
def test_hr_sends_shortlist():
    recruit.check_app(app("approval", shortlist=sent()), app(), HR, True, REQ, CO)


def test_someone_else_cannot_send_shortlist():
    with pytest.raises(Problem, match="only HR and the hiring manager"):
        recruit.check_app(app("approval", shortlist=sent(by=OTHER)), app(), OTHER, False, REQ, CO)


def test_shortlist_cannot_be_sent_decided():
    sl = sent(); sl["approvers"][0]["decision"] = "approve"
    with pytest.raises(Problem, match="already decided"):
        recruit.check_app(app("approval", shortlist=sl), app(), HR, True, REQ, CO)


def test_approver_decides_for_themselves_and_moves_to_interview():
    old = app("approval", shortlist=sent())
    new = app("interview", shortlist=decide(old["shortlist"], MGMT, "approve"))
    assert new["shortlist"]["status"] == "approved"
    recruit.check_app(new, old, MGMT, False, REQ, CO)


def test_nobody_decides_for_another_approver_not_even_hr():
    old = app("approval", shortlist=sent())
    new = app("interview", shortlist=decide(old["shortlist"], MGMT, "approve"))
    with pytest.raises(Problem, match="each approver decides only for themselves"):
        recruit.check_app(new, old, HR, True, REQ, CO)


def test_reject_needs_reason():
    old = app("approval", shortlist=sent())
    with pytest.raises(Problem, match="reason"):
        recruit.check_app(app("rejected", shortlist=decide(old["shortlist"], MGMT, "reject")), old, MGMT, False, REQ, CO)
    recruit.check_app(app("rejected", shortlist=decide(old["shortlist"], MGMT, "reject", "Too junior")), old, MGMT, False, REQ, CO)


def test_status_must_match_decisions():
    old = app("approval", shortlist=sent(rule="all"))
    sl = decide(old["shortlist"], MGMT, "approve"); assert sl["status"] == "pending"
    sl["status"] = "approved"                                      # one of two approvers: not yet
    with pytest.raises(Problem, match="does not match"):
        recruit.check_app(app("approval", shortlist=sl), old, MGMT, False, REQ, CO)


def test_all_rule():
    sl = sent(rule="all")
    sl = decide(sl, HM, "approve"); assert sl["status"] == "pending"
    sl2 = decide(sl, MGMT, "approve"); assert sl2["status"] == "approved"
    sl3 = decide(sl, MGMT, "reject", "no"); assert sl3["status"] == "rejected"
    sl4 = decide(sl, MGMT, "hold", "later"); assert sl4["status"] == "hold"


def test_any_rule_latest_decision_counts():
    sl = decide(sent(), MGMT, "hold", "wait", at=5); assert sl["status"] == "hold"
    sl = decide(sl, MGMT, "approve", at=9); assert sl["status"] == "approved"


def test_no_interview_stage_without_approval():
    with pytest.raises(Problem, match="not approved"):
        recruit.check_app(app("interview"), app("screening"), HR, True, REQ, CO)
    recruit.check_app(app("interview"), app("screening"), HR, True, REQ, {"rflow": {"slOn": False}})


def test_hr_can_skip_with_reason():
    sk = {"status": "skipped", "by": HR, "sentAt": 3, "skipReason": "Walk-in, MD met him"}
    recruit.check_app(app("interview", shortlist=sk), app("screening"), HR, True, REQ, CO)
    with pytest.raises(Problem, match="only HR"):
        recruit.check_app(app("interview", shortlist=sk), app("screening"), HM, False, REQ, CO)
    with pytest.raises(Problem, match="reason"):
        recruit.check_app(app("interview", shortlist={**sk, "skipReason": ""}), app("screening"), HR, True, REQ, CO)


def test_new_interview_needs_approval():
    with pytest.raises(Problem):
        recruit.check_new_interview(app("screening"), CO)
    recruit.check_new_interview(app("interview"), CO)
    recruit.check_new_interview(app("approval", shortlist={"status": "approved"}), CO)


def test_stranger_cannot_move_stage():
    with pytest.raises(Problem, match="only HR and the hiring manager move"):
        recruit.check_app(app("rejected"), app("screening"), OTHER, False, REQ, CO)


# ---------------------------------------------------------------- final selection
def proposal(dec="select", by=HR, rnd=1):
    return {"proposed": dec, "rank": 1, "note": "", "by": by, "at": 1, "round": rnd, "mgrId": HM, "status": "proposed", "final": ""}


def test_hr_proposes_manager_decides():
    old = app("interview")
    new = app("interview", sel=proposal())
    recruit.check_app(new, old, HR, True, REQ, CO)
    dec = app("selected", sel={**proposal(), "mgr": {"decision": "select", "by": HM, "at": 2}, "status": "decided", "final": "select"})
    recruit.check_app(dec, new, HM, False, REQ, CO)


def test_hr_cannot_decide_for_manager():
    new = app("interview", sel=proposal())
    dec = app("selected", sel={**proposal(), "mgr": {"decision": "select", "by": HR, "at": 2}, "status": "decided", "final": "select"})
    with pytest.raises(Problem, match="only the hiring manager"):
        recruit.check_app(dec, new, HR, True, REQ, CO)


def test_manager_overrules_with_reason():
    new = app("interview", sel=proposal())
    mgr = {"decision": "hold", "by": HM, "at": 2}
    with pytest.raises(Problem, match="reason"):
        recruit.check_app(app("interview", sel={**proposal(), "mgr": mgr, "status": "decided", "final": "hold"}), new, HM, False, REQ, CO)
    recruit.check_app(app("interview", sel={**proposal(), "mgr": {**mgr, "note": "Second opinion first"}, "status": "decided", "final": "hold"}), new, HM, False, REQ, CO)


def test_final_must_be_managers_decision():
    new = app("interview", sel=proposal())
    with pytest.raises(Problem, match="hiring manager's decision"):
        recruit.check_app(app("selected", sel={**proposal(), "mgr": {"decision": "reject", "by": HM, "note": "Not convinced"}, "status": "decided", "final": "select"}), new, HM, False, REQ, CO)


def test_selected_only_through_final_selection():
    with pytest.raises(Problem, match="final selection"):
        recruit.check_app(app("selected"), app("interview"), HR, True, REQ, CO)
    with pytest.raises(Problem, match="final selection"):
        recruit.check_app(app("offer"), app("interview"), HR, True, REQ, CO)
    recruit.check_app(app("selected"), app("interview"), HR, True, REQ, {"rflow": {"selOn": False}})


def test_proposal_goes_to_hiring_manager():
    with pytest.raises(Problem, match="hiring manager"):
        recruit.check_app(app("interview", sel={**proposal(), "mgrId": OTHER}), app("interview"), HR, True, REQ, CO)


def test_no_hiring_manager_hr_decides():
    req = {**REQ, "hiringMgr": "", "createdBy": HR}
    p = {**proposal(), "mgrId": ""}
    recruit.check_app(app("selected", sel={**p, "mgr": {"decision": "select", "by": HR}, "status": "decided", "final": "select"}), app("interview"), HR, True, req, CO)


# ---------------------------------------------------------------- signed offer
def test_acceptance_needs_signed_copy():
    old = app("offered", offer={"status": "issued"})
    with pytest.raises(Problem, match="signed"):
        recruit.check_app(app("accepted", offer={"status": "accepted"}), old, HR, True, REQ, CO)
    recruit.check_app(app("accepted", offer={"status": "accepted", "signed": {"fileId": "f1"}}), old, HR, True, REQ, CO)
    recruit.check_app(app("accepted", offer={"status": "accepted"}), old, HR, True, REQ, {"rflow": {"signOn": False}})


# ---------------------------------------------------------------- interview feedback and referrals
IV = {"id": "i1", "appId": "a1", "panel": [PANEL, HM], "status": "scheduled", "feedback": {}, "createdBy": HR}
OWNERS = {HM, HR}


def fb(rec="hire", **kw):
    return {"rating": 4, "rec": rec, "scores": {"tech": 4}, "comments": "Good", **kw}


def test_panel_member_gives_own_feedback():
    new = {**IV, "feedback": {PANEL: fb()}, "status": "completed"}
    recruit.check_interview(new, IV, PANEL, False, OWNERS)


def test_cannot_give_feedback_for_another():
    new = {**IV, "feedback": {HM: fb()}}
    with pytest.raises(Problem, match="own feedback"):
        recruit.check_interview(new, IV, PANEL, False, OWNERS)
    with pytest.raises(Problem, match="own feedback"):
        recruit.check_interview(new, IV, HR, True, OWNERS)          # HR, without saying they entered it


def test_hr_enters_paper_form_on_behalf():
    new = {**IV, "feedback": {PANEL: fb(enteredBy=HR)}}
    recruit.check_interview(new, IV, HR, True, OWNERS)


def test_refer_needs_someone():
    with pytest.raises(Problem, match="whom to refer"):
        recruit.check_interview({**IV, "feedback": {PANEL: fb("refer")}}, IV, PANEL, False, OWNERS)


def test_referral_made_and_answered():
    ref = {"id": "rf1", "to": MGMT, "by": PANEL, "at": 1, "question": "Enough for North?", "decision": ""}
    made = {**IV, "status": "completed", "feedback": {PANEL: fb("refer", referTo=[MGMT])}, "referrals": [ref]}
    recruit.check_interview(made, IV, PANEL, False, OWNERS)
    answered = copy.deepcopy(made); answered["referrals"][0].update(decision="hire", comments="Yes", decidedAt=2)
    recruit.check_interview(answered, made, MGMT, False, OWNERS)
    with pytest.raises(Problem, match="only the person referred to"):
        recruit.check_interview(answered, made, PANEL, False, OWNERS)


def test_panel_member_cannot_change_the_interview():
    with pytest.raises(Problem, match="only HR and the hiring manager change"):
        recruit.check_interview({**IV, "date": "2030-01-01"}, IV, PANEL, False, OWNERS)


def test_only_owner_schedules():
    with pytest.raises(Problem, match="schedule"):
        recruit.check_interview(IV, None, PANEL, False, OWNERS)
    recruit.check_interview(IV, None, HM, False, OWNERS)
