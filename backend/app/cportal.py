"""2.19: the candidate portal.

A candidate who has created a candidate sign-in (2.17) sees, besides their details form:

* their applications: for each job, where it stands (under review, interviews, selected, not selected, offer, joined),
  shown as steps; never HR's notes, the panel's feedback or management's decisions;
* their interviews: round, date and time, online link, venue or phone, the panel's names, and whether each
  happened, was moved or was cancelled;
* their offer: the letter exactly as HR issued it (kept on the offer when it is issued), and they can accept it
  with a typed signature (and the signed copy if they have one), decline it, or ask for changes, which becomes a
  negotiation round that HR answers;
* their messages with HR, both ways: HR writes from the candidate's page and the candidate from the portal, and
  each side also gets it by e-mail. Replies by plain e-mail come back into the same thread (inbox.py), matched by
  the reference in the subject.

What the candidate does is written here, on the server: the offer's response, their negotiation rounds and the
messages. A save from the app may carry an older copy of those records (HR had the page open); merge_app and
merge_cand keep what the candidate did, as candform.merge_from_app does for the form.

The thread lives on the candidate record (`msgs`, `msgRef` the reference used in e-mail subjects, `msgOwner` the
employee who handles it). Only this module writes it.
"""
import re
import secrets
import time
from datetime import date

class Problem(Exception):
    pass


MSG_MAX = 300                 # messages kept on a candidate
TEXT_MAX = 5000
SUBJECT_MAX = 160
FILES_MAX = 5
FILE_MB = 5
FILE_MIME = ("application/pdf", "image/jpeg", "image/png", "image/webp", "application/msword",
             "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
REF = re.compile(r"PD-([A-Z2-9]{8})")
REF_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

STAGES = ["review", "interviews", "selection", "offer", "joining"]
STEP_LABEL = {"review": "Application review", "interviews": "Interviews", "selection": "Selection", "offer": "Offer", "joining": "Joining"}
IV_MODE = {"f2f": "In person", "video": "Video call", "phone": "Phone call"}
IV_STATUS = {"scheduled": "Scheduled", "completed": "Done", "cancelled": "Cancelled", "noshow": "Missed"}


def now_ms() -> int:
    return int(time.time() * 1000)


def today() -> str:
    return date.today().isoformat()


def new_ref() -> str:
    return "".join(secrets.choice(REF_ALPHABET) for _ in range(8))


def ref_tag(cand: dict) -> str:
    return f"[Ref: PD-{cand['msgRef']}]" if cand.get("msgRef") else ""


def find_ref(subject: str) -> str:
    m = REF.search(subject or "")
    return m.group(1) if m else ""


# ---------------------------------------------------------------- what the candidate sees
def status_of(app: dict, ivs: list, today_: str | None = None) -> dict:
    """Where an application stands, in the candidate's words: key, label, tone, detail and the step reached."""
    t = today_ or today()
    st, o = app.get("stage"), app.get("offer") or {}
    live = [i for i in ivs if i.get("status") != "cancelled"]
    if st == "joined":
        return {"key": "joined", "label": "Joined", "tone": "ok", "detail": "Welcome aboard.", "step": "joining", "done": True}
    if st == "withdrawn":
        return {"key": "closed", "label": "Closed", "tone": "", "detail": "This application is closed.", "step": None, "stop": True}
    if st == "rejected":
        if o.get("status") == "declined":
            return {"key": "declined", "label": "You declined the offer", "tone": "", "detail": "This application is closed.", "step": "offer", "stop": True}
        reached = "interviews" if live else "review"
        return {"key": "notselected", "label": "Not selected", "tone": "bad",
                "detail": "Thank you for your time and interest. We will not be taking this application further.", "step": reached, "stop": True}
    if st == "accepted":
        return {"key": "accepted", "label": "Offer accepted", "tone": "ok", "detail": f"We look forward to you joining on {_dmy(o.get('doj'))}.", "step": "joining"}
    if st == "offered" and o.get("status") == "issued":
        return {"key": "offer", "label": "Offer made", "tone": "ok", "detail": "Your offer letter is below. Please accept it, decline it or ask for changes.", "step": "offer"}
    if st == "offered" and o.get("status") == "declined":
        return {"key": "declined", "label": "You declined the offer", "tone": "", "detail": "HR will be in touch.", "step": "offer"}
    if st in ("selected", "offer", "offered"):
        again = bool(o.get("versions"))
        return {"key": "selected", "label": "Selected", "tone": "ok",
                "detail": "A revised offer is being prepared." if again else "Congratulations. Your offer is being prepared.", "step": "offer" if again else "selection"}
    if st == "interview":
        nxt = sorted((i for i in live if i.get("status") == "scheduled" and (i.get("date") or "") >= t), key=lambda i: (i.get("date") or "", i.get("start") or ""))
        if nxt:
            return {"key": "interview", "label": "Interview scheduled", "tone": "info",
                    "detail": f"{nxt[0].get('round') or 'Interview'} on {_dmy(nxt[0].get('date'))} at {nxt[0].get('start') or ''}.", "step": "interviews"}
        if live and all(i.get("status") in ("completed", "noshow") for i in live):
            return {"key": "decision", "label": "Interviews done", "tone": "info", "detail": "Thank you. We are reviewing the interviews and will let you know.", "step": "selection"}
        return {"key": "interviews", "label": "Interviews", "tone": "info", "detail": "We will send you the interview details.", "step": "interviews"}
    return {"key": "review", "label": "Under review", "tone": "", "detail": "We are reviewing your application.", "step": "review"}


def steps_of(status: dict) -> list:
    reached = status.get("step")
    k = STAGES.index(reached) if reached in STAGES else -1
    out = []
    for n, s in enumerate(STAGES):
        if status.get("done") or n < k:
            state = "done"
        elif n == k:
            state = "stop" if status.get("stop") else "now"
        else:
            state = "todo"
        out.append({"key": s, "label": STEP_LABEL[s], "state": state})
    return out


def _dmy(iso) -> str:
    s = str(iso or "")
    return f"{s[8:10]}-{s[5:7]}-{s[0:4]}" if len(s) >= 10 else s


def interview_view(i: dict, names: dict) -> dict:
    return {"id": i.get("id"), "round": i.get("round") or "Interview", "date": i.get("date"), "start": i.get("start"), "duration": int(i.get("duration") or 45),
            "mode": i.get("mode"), "modeLabel": IV_MODE.get(i.get("mode"), ""), "link": i.get("link") if i.get("mode") == "video" else "",
            "venue": i.get("venue") if i.get("mode") == "f2f" else "", "status": i.get("status"), "statusLabel": IV_STATUS.get(i.get("status"), ""),
            "panel": [names.get(p, "") for p in (i.get("panel") or []) if names.get(p)]}


def offer_view(app: dict, t: str | None = None) -> dict | None:
    o = app.get("offer") or {}
    if o.get("status") not in ("issued", "accepted", "declined") or not o.get("letterNo"):
        return None
    t = t or today()
    expired = bool(o.get("expiry")) and o["expiry"] < t
    rounds = [x for x in (app.get("nego") or []) if x.get("viaPortal")]
    open_round = next((x for x in rounds if x.get("outcome") == "open"), None)
    can = o.get("status") == "issued" and app.get("stage") == "offered" and not expired
    s = o.get("signed") or {}
    return {"letterNo": o.get("letterNo"), "issuedAt": o.get("issuedAt"), "ctc": o.get("ctc"), "doj": o.get("doj"), "joiningBonus": o.get("joiningBonus") or 0,
            "expiry": o.get("expiry"), "expired": expired, "status": o.get("status"), "letterHtml": o.get("letterHtml") or "",
            "round": len(o.get("versions") or []) + 1, "canRespond": can, "canNegotiate": can and not open_round,
            "signed": {"name": (s.get("esign") or {}).get("name", ""), "at": s.get("at"), "file": bool(s.get("fileId"))} if o.get("status") == "accepted" else None,
            "declineReason": o.get("declineReason") if o.get("status") == "declined" else "",
            "negotiation": [{"id": x.get("id"), "at": x.get("at"), "askCtc": x.get("askCtc"), "askDoj": x.get("askDoj"), "askBonus": x.get("askBonus"),
                             "askOther": x.get("askOther"), "note": x.get("note"), "outcome": x.get("outcome"), "answer": x.get("answer") or "",
                             "ourCtc": x.get("ourCtc") if x.get("outcome") != "open" else None, "ourDoj": x.get("ourDoj") if x.get("outcome") != "open" else None,
                             "answeredAt": x.get("answeredAt")} for x in rounds]}


def message_view(m: dict, names: dict) -> dict:
    return {"id": m.get("id"), "dir": m.get("dir"), "at": m.get("at"), "subject": m.get("subject") or "", "text": m.get("text") or "",
            "from": "You" if m.get("dir") == "in" else (names.get(m.get("by")) or "HR"), "via": m.get("via"),
            "files": [{"id": f.get("id"), "name": f.get("name"), "size": f.get("size")} for f in (m.get("files") or [])],
            "job": m.get("job") or "", "read": bool(m.get("readAt")) if m.get("dir") == "out" else True}


# ---------------------------------------------------------------- what the candidate does
def _note(app: dict, text_: str, at: int):
    app["notes"] = [*(app.get("notes") or []), {"at": at, "by": "candidate", "text": text_}]


def _stage(app: dict, stage: str, note: str, at: int):
    app["stage"] = stage
    app["history"] = [*(app.get("history") or []), {"stage": stage, "at": at, "by": "candidate", "note": note}]


def _issued(app: dict, letter_no: str):
    o = app.get("offer") or {}
    if app.get("stage") != "offered" or o.get("status") != "issued":
        raise Problem("This offer can no longer be answered here. Write to HR in Messages.")
    if letter_no != o.get("letterNo"):
        raise Problem("The offer has changed since you opened it. Look at the latest offer and try again.")
    if o.get("expiry") and o["expiry"] < today():
        raise Problem(f"This offer expired on {_dmy(o['expiry'])}. Write to HR in Messages.")
    return o


def accept(app: dict, letter_no: str, name: str, agree: bool, cand_name: str, ip: str = "", signed_file: dict | None = None) -> dict:
    o = _issued(app, letter_no)
    name = " ".join(str(name or "").split())
    if not agree:
        raise Problem("Tick that you accept the offer on the terms in the letter.")
    if len(name) < 3:
        raise Problem("Type your full name as your signature.")
    if _squash(name) != _squash(cand_name):
        raise Problem(f"Type your name as it is on the offer letter: {cand_name}.")
    at = now_ms()
    o.update(status="accepted", respondedAt=at, respondedVia="portal",
             signed={"esign": {"name": name, "at": at, "ip": ip[:64]}, "at": at, "date": today(), "by": "candidate",
                     **({"fileId": signed_file["id"], "name": signed_file["name"]} if signed_file else {})})
    for x in app.get("nego") or []:
        if x.get("viaPortal") and x.get("outcome") == "open":
            x.update(outcome="held", answer="You accepted the offer as issued.", answeredAt=at)
    _stage(app, "accepted", f"Offer {o.get('letterNo')} accepted online, signed by {name}", at)
    app["followups"] = [*(app.get("followups") or []), {"id": secrets.token_hex(6), "due": max(today(), _minus_days(o.get("doj"), 3)),
                                                         "note": "Confirm joining date", "done": False, "by": "candidate"}]
    return app


def decline(app: dict, letter_no: str, reason: str) -> dict:
    o = _issued(app, letter_no)
    reason = str(reason or "").strip()[:1000]
    if len(reason) < 3:
        raise Problem("Tell us why, so that HR can understand.")
    at = now_ms()
    o.update(status="declined", respondedAt=at, respondedVia="portal", declineReason=reason)
    _note(app, f"Offer {o.get('letterNo')} declined online: {reason}", at)
    return app


def negotiate(app: dict, letter_no: str, ask: dict) -> dict:
    o = _issued(app, letter_no)
    if any(x.get("viaPortal") and x.get("outcome") == "open" for x in app.get("nego") or []):
        raise Problem("HR has not answered your last request yet.")
    def num(k):
        v = ask.get(k)
        if v in (None, ""):
            return ""
        try:
            n = round(float(v))
        except (TypeError, ValueError):
            raise Problem("Amounts are numbers of rupees.") from None
        if n < 0 or n > 10 ** 9:
            raise Problem("That amount does not look right.")
        return n
    ctc, bonus = num("askCtc"), num("askBonus")
    doj = str(ask.get("askDoj") or "")
    if doj and (not re.fullmatch(r"\d{4}-\d{2}-\d{2}", doj) or doj < today()):
        raise Problem("Choose a joining date from today on.")
    other, note = str(ask.get("askOther") or "").strip()[:500], str(ask.get("note") or "").strip()[:1000]
    if ctc == "" and bonus == "" and not doj and not other:
        raise Problem("Say what you would like changed: the CTC, the joining date, a joining bonus or something else.")
    at = now_ms()
    row = {"id": secrets.token_hex(6), "date": today(), "raised": "candidate", "viaPortal": True, "by": "candidate", "at": at,
           "askCtc": ctc, "askDoj": doj, "askBonus": bonus, "askOther": other, "note": note, "outcome": "open", "letterNo": o.get("letterNo")}
    app["nego"] = [*(app.get("nego") or []), row]
    _note(app, f"Asked online for changes to offer {o.get('letterNo')}", at)
    return row


def _squash(s: str) -> str:
    return re.sub(r"[^a-z]", "", str(s or "").lower())


def _minus_days(iso, n: int) -> str:
    try:
        from datetime import timedelta
        return (date.fromisoformat(iso) - timedelta(days=n)).isoformat()
    except (TypeError, ValueError):
        return today()


def describe_ask(row: dict, inr) -> str:
    parts = [f"CTC {inr(row['askCtc'])} a year" if row.get("askCtc") != "" and row.get("askCtc") is not None else "",
             f"joining on {_dmy(row['askDoj'])}" if row.get("askDoj") else "",
             f"joining bonus {inr(row['askBonus'])}" if row.get("askBonus") != "" and row.get("askBonus") is not None else "",
             row.get("askOther") or ""]
    return "; ".join(p for p in parts if p)


# ---------------------------------------------------------------- the thread
def add_message(cand: dict, *, direction: str, by: str, text_: str, subject: str = "", via: str = "app", app_id: str = "", job: str = "",
                files: list | None = None, key: str = "") -> dict | None:
    """Adds a message to the candidate's thread and returns it; None when `key` says it was sent already."""
    if key and any(m.get("key") == key for m in cand.get("msgs") or []):
        return None
    text_ = str(text_ or "").strip()
    if not text_ and not files:
        raise Problem("Write a message.")
    if len(text_) > TEXT_MAX:
        raise Problem(f"Keep a message to {TEXT_MAX} characters.")
    if len(files or []) > FILES_MAX:
        raise Problem(f"Attach up to {FILES_MAX} files.")
    if not cand.get("msgRef"):
        cand["msgRef"] = new_ref()
    m = {"id": secrets.token_hex(8), "dir": direction, "by": by, "at": now_ms(), "subject": str(subject or "").strip()[:SUBJECT_MAX],
         "text": text_, "via": via, "appId": app_id or "", "job": job or "", "files": files or []}
    if key:
        m["key"] = key
    cand["msgs"] = [*(cand.get("msgs") or []), m][-MSG_MAX:]
    if direction == "out" and by and not by.startswith("cand"):
        cand["msgOwner"] = by
    return m


def mark_read(cand: dict, direction: str) -> int:
    """Marks the other side's messages read: direction 'in' for HR reading the candidate's, 'out' for the candidate."""
    n, at = 0, now_ms()
    for m in cand.get("msgs") or []:
        if m.get("dir") == direction and not m.get("readAt"):
            m["readAt"] = at
            n += 1
    return n


def subject_for(cand: dict, subject: str) -> str:
    s = re.sub(r"\s*\[Ref: PD-[A-Z2-9]{8}\]", "", str(subject or "")).strip() or "Your application"
    return f"{s} {ref_tag(cand)}".strip()


# ---------------------------------------------------------------- saves from the app keep what the candidate did
SERVER_CAND = ("msgs", "msgRef", "msgOwner")
ASK = ("raised", "viaPortal", "by", "at", "date", "askCtc", "askDoj", "askBonus", "askOther", "note", "letterNo")
RESP = ("status", "respondedAt", "respondedVia", "signed", "declineReason")


def merge_cand(new: dict, old: dict | None) -> dict:
    """The thread is written only on the server: a save from the app keeps it as stored."""
    for k in SERVER_CAND:
        if old and k in old:
            new[k] = old[k]
        else:
            new.pop(k, None)
    return new


def merge_app(new: dict, old: dict | None) -> dict:
    """An application saved from the app: what the candidate did online stands even if the copy is older."""
    if not old:
        return new
    oo, no = old.get("offer") or {}, new.get("offer") or {}
    # the candidate answered this letter online and the app still has it as issued: an older copy
    if oo.get("respondedVia") == "portal" and oo.get("status") in ("accepted", "declined") and no.get("letterNo") == oo.get("letterNo") and no.get("status") == "issued":
        new["offer"] = {**no, **{k: oo[k] for k in RESP if k in oo}}
        if old.get("stage") == "accepted" and new.get("stage") == "offered":
            new["stage"] = "accepted"
    # the candidate's own rounds: their asks as they made them; HR's answers as HR saves them
    by_id = {x.get("id"): x for x in new.get("nego") or [] if isinstance(x, dict)}
    for x in old.get("nego") or []:
        if not x.get("viaPortal"):
            continue
        if x.get("id") in by_id:
            by_id[x["id"]].update({k: x[k] for k in ASK if k in x})
        else:
            new["nego"] = [*(new.get("nego") or []), x]
    if new.get("nego"):
        new["nego"] = sorted(new["nego"], key=lambda x: x.get("at") or 0)
    # notes, history and follow-ups the server added stay
    for k, key in (("notes", ("at", "by", "text")), ("history", ("at", "stage", "by")), ("followups", ("id",))):
        have = {tuple(x.get(f) for f in key) for x in new.get(k) or [] if isinstance(x, dict)}
        extra = [x for x in old.get(k) or [] if isinstance(x, dict) and x.get("by") == "candidate" and tuple(x.get(f) for f in key) not in have]
        if extra:
            new[k] = sorted([*(new.get(k) or []), *extra], key=lambda x: x.get("at") or 0) if k != "followups" else [*(new.get(k) or []), *extra]
    return new
