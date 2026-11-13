"""2.19: e-mail in the conversation between HR and a candidate, both ways.

Out: a message to the candidate (from HR, or a notice: interview, offer) is e-mailed to the candidate; a message
from the candidate (written in the portal or sent by e-mail) is e-mailed to the employee who handles the thread.
Every such e-mail carries the thread's reference in the subject, "[Ref: PD-XXXXXXXX]", and, when replies are
collected, a Reply-To of the replies mailbox.

In: when the group administrator sets up the replies mailbox (Settings › E-mail › Replies from candidates), a
background reader looks at it every two minutes over IMAP (a password, or Microsoft 365 with the same Entra app as
sending, which then needs IMAP.AccessAsApp). A new e-mail whose subject has a reference is added to that thread:

* from the candidate's e-mail address: a message from the candidate, passed on to HR;
* from an active employee of the candidate's company who is HR, handles the thread, or owns one of the candidate's
  requisitions: a message to the candidate, passed on to the candidate;
* anything else, automatic replies (out of office) and our own e-mails: left out, and noted in the audit log.

The quoted earlier e-mail under a reply is cut off; attachments (PDF, photos, Word, up to 5 MB, up to 5) are kept.
Each e-mail is read once: it is marked read in the mailbox and its Message-ID remembered.
"""
import email
import email.policy
import html as htmlmod
import imaplib
import json
import logging
import re
import threading
import time
from email.utils import parseaddr

from sqlalchemy import text

from . import config, cportal, email_templates, mailer, repo

log = logging.getLogger("peopledesk")
KV = "mailin"
POLL_SECONDS = 120
_lock = threading.Lock()


# ---------------------------------------------------------------- settings
def stored(conn) -> dict:
    v = conn.execute(text("SELECT data FROM app_kv WHERE k=:k"), {"k": KV}).scalar()
    try:
        return json.loads(v) if v else {}
    except ValueError:
        return {}


def save(conn, d: dict):
    conn.execute(text("INSERT INTO app_kv (k, data) VALUES (:k, :d) ON DUPLICATE KEY UPDATE data=VALUES(data)"), {"k": KV, "d": json.dumps(d)})


def settings(conn) -> dict:
    d = stored(conn)
    return {**d, "password": mailer.decrypt(d.get("password", ""))} if d else {}


def reply_to(conn) -> str:
    d = stored(conn)
    return (d.get("address") or "").strip() if d.get("on") else ""


def public(conn) -> dict:
    d = stored(conn)
    return {"on": bool(d.get("on")), "host": d.get("host", ""), "port": d.get("port", 993), "security": d.get("security", "ssl"),
            "auth": d.get("auth", "password"), "user": d.get("user", ""), "hasPassword": bool(d.get("password")), "folder": d.get("folder", "INBOX"),
            "address": d.get("address", ""), "lastRun": d.get("lastRun"), "lastResult": d.get("lastResult", "")}


# ---------------------------------------------------------------- reading an e-mail
QUOTE_START = [re.compile(p, re.I) for p in (
    r"^\s*On\b.{4,300}\bwrote:\s*$", r"^\s*-{2,}\s*Original Message\s*-{2,}", r"^\s*_{10,}\s*$", r"^\s*From:\s.+",
    r"^\s*-{5,}\s*Forwarded message", r"^\s*Sent from my \w+", r"^\s*Get Outlook for ")]


def strip_reply(t: str) -> str:
    """The new part of a reply: what is above the quoted earlier e-mail."""
    lines = (t or "").replace("\r\n", "\n").split("\n")
    out = []
    for n, ln in enumerate(lines):
        two = ln + " " + (lines[n + 1] if n + 1 < len(lines) else "")
        if any(p.match(ln) for p in QUOTE_START) or (QUOTE_START[0].match(two) and ln.strip().startswith("On ")):
            break
        if ln.startswith(">") and all(x.startswith(">") or not x.strip() for x in lines[n:]):
            break
        out.append(ln)
    s = "\n".join(out).strip()
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s or (t or "").strip()


def html_to_text(h: str) -> str:
    h = re.sub(r"(?is)<(script|style|head)[^>]*>.*?</\1>", "", h or "")
    h = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</li>", "\n", h)
    h = re.sub(r"(?s)<[^>]+>", "", h)
    return re.sub(r"[ \t]+\n", "\n", htmlmod.unescape(h)).strip()


def parse(raw: bytes) -> dict:
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    name, addr = parseaddr(str(msg.get("From", "")))
    auto = (str(msg.get("Auto-Submitted", "no")).lower() not in ("", "no") or msg.get("X-Autoreply") or msg.get("X-Autorespond")
            or str(msg.get("Precedence", "")).lower() in ("bulk", "auto_reply", "junk", "list")
            or re.match(r"(?i)^\s*(automatic reply|auto(matic)?[- ]?reply|out of (the )?office|undeliverable|delivery status)", str(msg.get("Subject", ""))))
    body, html_body, files = "", "", []
    for part in msg.walk():
        if part.is_multipart():
            continue
        disp = part.get_content_disposition()
        ctype = part.get_content_type()
        if disp == "attachment" or (disp == "inline" and part.get_filename()):
            data = part.get_payload(decode=True) or b""
            files.append((part.get_filename() or "attachment", data, ctype))
        elif ctype == "text/plain" and not body:
            body = part.get_content()
        elif ctype == "text/html" and not html_body:
            html_body = part.get_content()
    txt = body or html_to_text(html_body)
    return {"from": addr.lower(), "fromName": name, "subject": str(msg.get("Subject", "")), "text": strip_reply(txt), "files": files,
            "messageId": str(msg.get("Message-ID", "")).strip(), "auto": bool(auto)}


# ---------------------------------------------------------------- who the thread is with
def cand_by_ref(conn, ref: str):
    if not ref:
        return None
    d = conn.execute(text("SELECT data FROM candidates WHERE JSON_UNQUOTE(JSON_EXTRACT(data, '$.msgRef'))=:r LIMIT 1"), {"r": ref}).scalar()
    return repo.loads(d) if d else None


def hr_side(conn, cand: dict) -> set:
    """Employees who may write to the candidate by e-mail: HR of the company, the thread's owner, and the owners of
    the candidate's requisitions."""
    co = cand.get("companyId")
    ids = {cand.get("msgOwner")}
    for a in repo.records_where(conn, "apps", "cand_id", cand["id"]):
        r = repo.get_records(conn, "reqs", [a.get("reqId")]).get(a.get("reqId")) or {}
        ids |= {r.get("hiringMgr"), r.get("createdBy")}
    emps = repo.employees_index(conn)
    private = repo.registered_companies(conn)     # the group administrator does not write for a company that registered itself
    for e in emps.values():
        if e.get("status") != "exited" and ((e.get("role") == "super" and co not in private) or (e.get("role") == "hr" and (e.get("companyId") == co or co in (e.get("hrCompanies") or [])))):
            ids.add(e["id"])
    return {i for i in ids if i and (emps.get(i) or {}).get("status") != "exited"}


def handler_of(conn, cand: dict) -> str:
    """The employee who gets the candidate's messages: the thread's owner, else whoever sent the form link, else
    whoever added the candidate."""
    emps = repo.employees_index(conn)
    for i in (cand.get("msgOwner"), (cand.get("form") or {}).get("sentBy"), cand.get("createdBy")):
        if i and (emps.get(i) or {}).get("status") not in (None, "exited") and (emps.get(i) or {}).get("email"):
            return i
    return ""


def app_link(conn, cand: dict, app_id: str = "") -> str:
    """Where HR answers: the application page (the message's job, else the latest), else the candidate pool."""
    apps = repo.records_where(conn, "apps", "cand_id", cand["id"])
    a = next((x for x in apps if x.get("id") == app_id), None) or (sorted(apps, key=lambda x: x.get("createdAt") or 0)[-1] if apps else None)
    return f"{config.APP_URL}/#/app/{a['id']}" if a else f"{config.APP_URL}/#/cands"


def job_of(conn, cand: dict, app_id: str = "") -> str:
    apps = repo.records_where(conn, "apps", "cand_id", cand["id"])
    a = next((x for x in apps if x.get("id") == app_id), None) or (sorted(apps, key=lambda x: x.get("createdAt") or 0)[-1] if apps else None)
    if not a:
        return ""
    return (repo.get_records(conn, "reqs", [a.get("reqId")]).get(a.get("reqId")) or {}).get("title", "")


# ---------------------------------------------------------------- sending
def _company(conn, cand: dict) -> dict:
    return repo.get_records(conn, "companies", [cand.get("companyId")]).get(cand.get("companyId")) or {}


def to_candidate(conn, cand: dict, m: dict, send=None) -> str:
    """E-mails a message to the candidate. Returns '' when sent, else why not."""
    to = (cand.get("email") or "").strip()
    if not to:
        return "the candidate has no e-mail address; it is in their portal"
    if not mailer.configured():
        return "e-mail is not set up on the server; it is in their portal"
    emps = repo.employees_index(conn)
    co = _company(conn, cand)
    sender = emps.get(m.get("by")) or {}
    rt = reply_to(conn)
    subject, body = email_templates.render(conn, cand.get("companyId"), "candidate.message", {
        "firstName": (cand.get("name") or "").split(" ")[0], "subject": m.get("subject") or "Your application", "text": m.get("text", ""),
        "sender": f"{sender.get('firstName', '')} {sender.get('lastName', '')}".strip() or "HR", "company": co.get("legalName") or co.get("name", ""),
        "link": config.APP_URL or "", "replyLine": "Reply to this e-mail, or sign in to your candidate portal to reply." if rt else "Sign in to your candidate portal to reply.",
        "filesLine": f"Attached in your candidate portal: {', '.join(f['name'] for f in m.get('files') or [])}." if m.get("files") else ""})
    try:
        (send or mailer.send)([to], cportal.subject_for(cand, subject), body, reply_to=rt or None)
        return ""
    except Exception as e:  # noqa: BLE001
        log.warning("Candidate mail failed: %s", e)
        return "the e-mail server refused it; it is in their portal"


def to_hr(conn, cand: dict, m: dict, send=None) -> str:
    """E-mails a message from the candidate to the employee who handles the thread."""
    who = handler_of(conn, cand)
    emps = repo.employees_index(conn)
    if not who or not mailer.configured():
        return "not e-mailed; it is in Approvals"
    rt = reply_to(conn)
    subject, body = email_templates.render(conn, cand.get("companyId"), "candidate.toHr", {
        "firstName": emps[who].get("firstName", ""), "candidate": cand.get("name", ""), "job": m.get("job") or job_of(conn, cand, m.get("appId", "")),
        "subject": m.get("subject") or "Message", "text": m.get("text", ""), "via": " by e-mail" if m.get("via") == "email" else " in the candidate portal",
        "filesLine": f"Attached: {', '.join(f['name'] for f in m.get('files') or [])} (open them in PeopleDesk)." if m.get("files") else "",
        "replyLine": "Reply to this e-mail to answer the candidate, or answer in PeopleDesk." if rt else "Answer in PeopleDesk.",
        "link": app_link(conn, cand, m.get("appId", ""))})
    try:
        (send or mailer.send)([emps[who]["email"]], cportal.subject_for(cand, subject), body, reply_to=rt or None)
        return ""
    except Exception as e:  # noqa: BLE001
        log.warning("Mail to HR failed: %s", e)
        return "not e-mailed; it is in Approvals"


# ---------------------------------------------------------------- an e-mail that came in
def take(conn, raw: bytes, store, send=None) -> str:
    """Adds one received e-mail to its thread. store(data, name, mime, company_id, owner) -> file id.
    Returns what happened: candidate | hr | auto | noref | unknown | self."""
    p = parse(raw)
    own = {(mailer.settings().get("fromAddr") or "").lower(), (reply_to(conn) or "").lower()} - {""}
    if p["from"] in own:
        return "self"
    if p["auto"]:
        return "auto"
    cand = cand_by_ref(conn, cportal.find_ref(p["subject"]))
    if not cand:
        return "noref"
    emps = repo.employees_index(conn)
    if p["from"] and p["from"] == (cand.get("email") or "").strip().lower():
        direction, by = "in", "cand"
    else:
        emp = next((e for e in emps.values() if (e.get("email") or "").lower() == p["from"] and e.get("status") != "exited"), None)
        if not emp or emp["id"] not in hr_side(conn, cand):
            repo.audit_add(conn, "E-mail to a candidate thread left out", f"from {p['from']} for {cand.get('name', '')}", None, module="recruitment",
                           ref_type="candidate", ref_id=cand["id"])
            return "unknown"
        direction, by = "out", emp["id"]
    files = []
    for name, data, mime in p["files"][:cportal.FILES_MAX]:
        if mime in cportal.FILE_MIME and 0 < len(data) <= cportal.FILE_MB * 1024 * 1024:
            fid = store(data, name, mime, cand.get("companyId"), "cd:" + cand["id"] if direction == "in" else by)
            files.append({"id": fid, "name": name, "size": len(data), "mime": mime})
    subject = re.sub(r"\s*\[Ref: PD-[A-Z2-9]{8}\]", "", re.sub(r"(?i)^((re|fw|fwd|aw)\s*:\s*)+", "", p["subject"])).strip()
    if subject.startswith(cand.get("name", "") + ":"):
        subject = subject[len(cand.get("name", "")) + 1:].strip()
    m = cportal.add_message(cand, direction=direction, by=by, text_=p["text"] or "(no text)", subject=subject, via="email",
                            job=job_of(conn, cand), files=files, key="mail:" + p["messageId"] if p["messageId"] else "")
    if not m:
        return "self"
    repo.upsert(conn, "cands", [cand], by if direction == "out" else None)
    repo.audit_add(conn, "E-mail from the candidate" if direction == "in" else "E-mail to the candidate", cand.get("name", ""),
                   None if direction == "in" else by, module="recruitment", ref_type="candidate", ref_id=cand["id"])
    repo.bump_rev(conn)
    if direction == "in":
        to_hr(conn, cand, m, send)
    else:
        to_candidate(conn, cand, m, send)
    return "candidate" if direction == "in" else "hr"


# ---------------------------------------------------------------- the mailbox
def _connect(s: dict):
    port = int(s.get("port") or 993)
    imap = imaplib.IMAP4_SSL(s["host"], port, timeout=30) if (s.get("security") or "ssl") == "ssl" else imaplib.IMAP4(s["host"], port, timeout=30)
    if s.get("security") == "starttls":
        imap.starttls()
    if s.get("auth") == "m365":
        token = mailer._m365_token(mailer.settings())                           # noqa: SLF001 - same Entra app as sending
        user = s.get("user") or s.get("address")
        imap.authenticate("XOAUTH2", lambda _: f"user={user}\x01auth=Bearer {token}\x01\x01".encode())
    else:
        imap.login(s.get("user") or "", s.get("password") or "")
    return imap


def run_once(engine, store, send=None) -> str:
    """Reads the replies mailbox once. Returns a short account for the settings page."""
    with engine.connect() as conn:
        s = settings(conn)
    if not s.get("on") or not s.get("host"):
        return "off"
    counts: dict = {}
    with _lock:
        imap = _connect(s)
        try:
            typ, _ = imap.select(s.get("folder") or "INBOX")
            if typ != "OK":
                raise RuntimeError(f"the folder {s.get('folder') or 'INBOX'} was not found")
            typ, data = imap.search(None, "UNSEEN")
            for num in (data[0].split() if data and data[0] else [])[:50]:
                typ, parts = imap.fetch(num, "(BODY.PEEK[])")
                raw = next((p[1] for p in parts if isinstance(p, tuple)), b"")
                try:
                    with engine.begin() as conn:
                        what = take(conn, raw, store, send)
                except Exception as e:  # noqa: BLE001 - one bad e-mail must not stop the rest
                    log.warning("A received e-mail could not be taken: %s", e)
                    what = "error"
                counts[what] = counts.get(what, 0) + 1
                imap.store(num, "+FLAGS", "\\Seen")
        finally:
            try:
                imap.logout()
            except Exception:  # noqa: BLE001
                pass
    words = {"candidate": "from candidates", "hr": "from HR", "noref": "without a reference", "unknown": "from people not in the thread",
             "auto": "automatic replies", "self": "our own", "error": "could not be read"}
    return ", ".join(f"{n} {words.get(k, k)}" for k, n in counts.items()) or "no new e-mail"


def _note_run(engine, result: str):
    with engine.begin() as conn:
        d = stored(conn)
        if d:
            d.update(lastRun=int(time.time() * 1000), lastResult=result[:300])
            save(conn, d)


def start(engine, store, send=None):
    def loop():
        time.sleep(20)
        while True:
            try:
                r = run_once(engine, store, send)
                if r != "off":
                    _note_run(engine, r)
            except Exception as e:  # noqa: BLE001 - the reader must keep running
                log.warning("Replies mailbox: %s", e)
                try:
                    _note_run(engine, f"error: {e}")
                except Exception:  # noqa: BLE001
                    pass
            time.sleep(POLL_SECONDS)
    threading.Thread(target=loop, name="mail-replies", daemon=True).start()
