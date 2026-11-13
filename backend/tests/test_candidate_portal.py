"""2.19: the candidate portal (app/cportal.py) and reading replies (app/cmail.py). No database needed.
    cd backend && python -m pytest tests/test_candidate_portal.py -q
"""
import copy
from datetime import date, timedelta
from email.message import EmailMessage

import pytest

from app import cmail, cportal
from app.cportal import Problem

T = date.today().isoformat()
LATER = (date.today() + timedelta(days=10)).isoformat()
PAST = (date.today() - timedelta(days=1)).isoformat()


def offered(**o):
    return {"id": "a1", "candId": "c1", "stage": "offered", "history": [], "notes": [],
            "offer": {"status": "issued", "letterNo": "OL/1", "ctc": 800000, "doj": LATER, "expiry": LATER, "letterHtml": "<p>Offer</p>", **o}}


# ---------------------------------------------------------------- what the candidate sees
@pytest.mark.parametrize("stage,ivs,key", [
    ("sourced", [], "review"), ("approval", [], "review"),
    ("interview", [{"status": "scheduled", "date": LATER, "start": "10:00", "round": "First round"}], "interview"),
    ("interview", [{"status": "completed"}], "decision"),
    ("selected", [], "selected"), ("offer", [], "selected"), ("accepted", [], "accepted"), ("joined", [], "joined"),
    ("rejected", [{"status": "completed"}], "notselected"), ("withdrawn", [], "closed")])
def test_status(stage, ivs, key):
    assert cportal.status_of({"stage": stage, "offer": {}}, ivs)["key"] == key


def test_internal_stages_never_named():
    for stage in ("sourced", "screening", "approval"):
        s = cportal.status_of({"stage": stage}, [])
        assert "approval" not in s["label"].lower() and "management" not in s["detail"].lower()


def test_offer_made_and_steps():
    s = cportal.status_of(offered(), [])
    assert s["key"] == "offer"
    assert [x["state"] for x in cportal.steps_of(s)] == ["done", "done", "done", "now", "todo"]
    nr = cportal.status_of({"stage": "rejected"}, [{"status": "completed"}])
    assert [x["state"] for x in cportal.steps_of(nr)] == ["done", "stop", "todo", "todo", "todo"]


def test_offer_view_only_when_issued():
    assert cportal.offer_view({"stage": "offer", "offer": {"status": "approved", "letterNo": ""}}) is None
    v = cportal.offer_view(offered())
    assert v["canRespond"] and v["canNegotiate"] and v["letterHtml"] == "<p>Offer</p>"
    assert not cportal.offer_view(offered(expiry=PAST))["canRespond"]


def test_interview_view_hides_feedback():
    v = cportal.interview_view({"id": "i1", "round": "First", "mode": "video", "link": "https://x", "venue": "Office", "panel": ["e1"],
                                "feedback": {"e1": {"rec": "reject"}}, "status": "completed"}, {"e1": "Rahul Menon"})
    assert "feedback" not in v and v["venue"] == "" and v["link"] == "https://x" and v["panel"] == ["Rahul Menon"]


# ---------------------------------------------------------------- what the candidate does
def test_accept_needs_name_as_on_letter_and_tick():
    with pytest.raises(Problem, match="Tick"):
        cportal.accept(offered(), "OL/1", "Rohit Verma", False, "Rohit Verma")
    with pytest.raises(Problem, match="as it is on the offer"):
        cportal.accept(offered(), "OL/1", "Someone Else", True, "Rohit Verma")
    a = cportal.accept(offered(), "OL/1", "rohit  verma", True, "Rohit Verma", "1.2.3.4")
    assert a["stage"] == "accepted" and a["offer"]["status"] == "accepted" and a["offer"]["respondedVia"] == "portal"
    assert a["offer"]["signed"]["esign"]["name"] == "rohit verma" and a["history"][-1]["by"] == "candidate"


def test_cannot_answer_old_or_expired_or_answered_offer():
    with pytest.raises(Problem, match="changed"):
        cportal.decline(offered(), "OL/0", "Too far")
    with pytest.raises(Problem, match="expired"):
        cportal.decline(offered(expiry=PAST), "OL/1", "Too far")
    a = cportal.decline(offered(), "OL/1", "Took another offer")
    assert a["offer"]["status"] == "declined" and a["stage"] == "offered"
    with pytest.raises(Problem, match="no longer"):
        cportal.accept(a, "OL/1", "Rohit Verma", True, "Rohit Verma")


def test_negotiate_one_open_round_at_a_time():
    a = offered()
    with pytest.raises(Problem, match="Say what"):
        cportal.negotiate(a, "OL/1", {})
    with pytest.raises(Problem, match="from today"):
        cportal.negotiate(a, "OL/1", {"askDoj": PAST})
    row = cportal.negotiate(a, "OL/1", {"askCtc": "900000", "note": "Market rate"})
    assert row["askCtc"] == 900000 and row["outcome"] == "open" and row["viaPortal"]
    with pytest.raises(Problem, match="not answered"):
        cportal.negotiate(a, "OL/1", {"askCtc": 950000})
    assert not cportal.offer_view(a)["canNegotiate"]
    cportal.accept(a, "OL/1", "Rohit Verma", True, "Rohit Verma")
    assert a["nego"][0]["outcome"] == "held"


# ---------------------------------------------------------------- the thread
def test_messages_and_keys():
    c = {"id": "c1", "name": "Rohit Verma"}
    m = cportal.add_message(c, direction="out", by="hr1", text_="Hello", subject="Hi", key="offer:OL/1")
    assert c["msgRef"] and c["msgOwner"] == "hr1" and m["dir"] == "out"
    assert cportal.add_message(c, direction="out", by="hr1", text_="Hello again", key="offer:OL/1") is None
    with pytest.raises(Problem):
        cportal.add_message(c, direction="in", by="cand", text_="  ")
    cportal.add_message(c, direction="in", by="cand", text_="Thanks")
    assert cportal.mark_read(c, "in") == 1 and cportal.mark_read(c, "in") == 0
    s = cportal.subject_for(c, "Re: Hi [Ref: PD-AAAAAAAA]")
    assert s.endswith(f"[Ref: PD-{c['msgRef']}]") and s.count("[Ref:") == 1
    assert cportal.find_ref(s) == c["msgRef"]


# ---------------------------------------------------------------- saves from the app keep what the candidate did
def test_stale_save_keeps_acceptance():
    old = offered(); cportal.accept(old, "OL/1", "Rohit Verma", True, "Rohit Verma")
    stale = offered(); stale["notes"] = [{"at": 1, "by": "hr1", "text": "HR note"}]
    merged = cportal.merge_app(copy.deepcopy(stale), old)
    assert merged["offer"]["status"] == "accepted" and merged["stage"] == "accepted" and merged["offer"]["signed"]
    assert any(n["by"] == "hr1" for n in merged["notes"]) and any(h["by"] == "candidate" for h in merged["history"])


def test_new_round_after_decline_is_not_undone():
    old = offered(); cportal.decline(old, "OL/1", "Low pay")
    new = copy.deepcopy(old); new["offer"].update(status="draft", letterNo="", versions=[{"letterNo": "OL/1"}]); new["stage"] = "offer"
    merged = cportal.merge_app(copy.deepcopy(new), old)
    assert merged["offer"]["status"] == "draft" and merged["stage"] == "offer"


def test_candidates_ask_kept_and_hr_answer_taken():
    old = offered(); row = cportal.negotiate(old, "OL/1", {"askCtc": 900000})
    stale = offered()                                                         # HR's copy without the round
    assert cportal.merge_app(copy.deepcopy(stale), old)["nego"][0]["id"] == row["id"]
    answered = copy.deepcopy(old); answered["nego"][0].update(askCtc=1, outcome="agreed", ourCtc=850000, answer="We can do 8.5")
    m = cportal.merge_app(answered, old)["nego"][0]
    assert m["askCtc"] == 900000 and m["ourCtc"] == 850000 and m["outcome"] == "agreed"


def test_thread_written_only_on_server():
    old = {"id": "c1", "msgs": [{"id": "m1"}], "msgRef": "ABCDEFGH"}
    assert cportal.merge_cand({"id": "c1", "msgs": [], "name": "x"}, old)["msgs"] == [{"id": "m1"}]
    assert "msgs" not in cportal.merge_cand({"id": "c2", "msgs": [{"id": "forged"}]}, None)


# ---------------------------------------------------------------- reading replies
def test_strip_reply():
    gmail = "Yes, Thursday works.\n\nOn Tue, 17 Nov 2026 at 10:00, Priya Shah <hr@aequm.in> wrote:\n> Can you come on Thursday?\n"
    assert cmail.strip_reply(gmail) == "Yes, Thursday works."
    outlook = "Thanks, attached.\n\n________________________________\nFrom: Priya Shah\nSent: Tuesday\nSubject: Documents"
    assert cmail.strip_reply(outlook) == "Thanks, attached."
    wrapped = "Fine by me.\n\nOn Tue, 17 Nov 2026 at 10:00, Priya Shah <hr@aequm.in>\nwrote:\n> old"
    assert cmail.strip_reply(wrapped) == "Fine by me."
    assert cmail.strip_reply("Just this") == "Just this"


def test_parse_reply_with_attachment():
    m = EmailMessage(); m["From"] = "Rohit Verma <Rohit@Mail.com>"; m["Subject"] = "Re: Documents for joining [Ref: PD-ABCDEFGH]"; m["Message-ID"] = "<x1@mail>"
    m.set_content("Here is my relieving letter.\n\nOn Mon, someone wrote:\n> please send")
    m.add_attachment(b"%PDF-1.4 test", maintype="application", subtype="pdf", filename="relieving.pdf")
    p = cmail.parse(m.as_bytes())
    assert p["from"] == "rohit@mail.com" and p["text"] == "Here is my relieving letter." and not p["auto"]
    assert cportal.find_ref(p["subject"]) == "ABCDEFGH" and p["files"][0][0] == "relieving.pdf" and p["files"][0][2] == "application/pdf"


def test_out_of_office_is_left_out():
    m = EmailMessage(); m["From"] = "x@y.com"; m["Subject"] = "Automatic reply: Interview [Ref: PD-ABCDEFGH]"; m.set_content("I am away")
    assert cmail.parse(m.as_bytes())["auto"]
    m2 = EmailMessage(); m2["From"] = "x@y.com"; m2["Subject"] = "Interview"; m2["Auto-Submitted"] = "auto-replied"; m2.set_content("away")
    assert cmail.parse(m2.as_bytes())["auto"]


def test_html_only_reply():
    m = EmailMessage(); m["From"] = "a@b.com"; m["Subject"] = "Re: x"
    m.set_content("<div>Thanks!<br>See you</div><div>On Mon, X wrote:</div><blockquote>old</blockquote>", subtype="html")
    assert cmail.parse(m.as_bytes())["text"].startswith("Thanks!\nSee you")
