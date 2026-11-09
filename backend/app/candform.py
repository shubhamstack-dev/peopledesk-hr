"""
PeopleDesk 2.11: the application form a candidate fills in through a link.

HR asks a candidate (from the candidate pool or one of their applications) to fill in their details: personal
details, address, emergency contact, identity numbers, bank account, education, previous jobs, references,
family, and their CV. The candidate opens a signed link without signing in, saves as they go and sends the form.
HR sees it on the candidate and can ask for changes; when the candidate joins, HR converts them into an employee
and the details become the employee record.

The form lives on the candidate record (`form`). Only this module writes what the candidate entered
(`form.data`, `form.savedAt`, `form.submittedAt`) and the link's nonce: a save from the app keeps those as stored
and may only ask for changes (`returned`) or close the form (`closed`, done on joining).

The link is valid for 14 days and only while the form is open (sent, being filled in, or returned for changes).
Sending a new link makes older ones stop working.
"""
import base64
import re
import time
import uuid
from datetime import date

import jwt

from . import repo
from .config import JWT_SECRET

LINK_DAYS = 14
OPEN = {"sent", "draft", "returned"}
CV_MAX = 2 * 1024 * 1024
CV_MIME = {"application/pdf", "application/msword", "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
           "application/rtf", "text/rtf", "text/plain"}
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
YM = re.compile(r"^\d{4}-\d{2}$")
PAN = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
IFSC = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
PHONE = re.compile(r"^\+?[\d\s-]{8,16}$")

S, L = 120, 1500          # short and long text
# What the form holds. Kinds: a number (maximum length of text), "date", "month", "num", "bool"
FIELDS = {
    "firstName": S, "lastName": S, "gender": 2, "dob": "date", "marital": 20, "anniversary": "date", "blood": 12,
    "phone": 20, "altPhone": 20, "nationality": 40, "fatherName": S,
    "address": 400, "addrCity": 80, "addrState": 80, "addrPin": 12, "addrCountry": 60,
    "permAddress": 400,
    "emergencyName": S, "emergencyRelation": 40, "emergencyPhone": 20,
    "pan": 10, "aadhaar": 14, "uan": 12, "bankName": 80, "bankAcc": 24, "ifsc": 11,
    "currentCompany": S, "currentTitle": S, "expYears": "num", "currentCtc": "num", "expectedCtc": "num", "noticeDays": "num",
    "location": 80, "skills": 600, "languages": 200, "linkedin": 200, "about": L, "declaration": "bool",
}
LISTS = {
    "education": {"level": 40, "qualification": S, "specialisation": S, "institution": S, "university": S, "mode": 12,
                  "fromYear": 4, "toYear": 4, "score": 20, "scoreType": 8},
    "prevJobs": {"employer": S, "designation": S, "location": 80, "from": "month", "to": "month", "empCode": 40,
                 "lastCtc": "num", "reason": 300, "duties": L, "contact": 200},
    "references": {"name": S, "organisation": S, "designation": S, "relation": 200, "phone": 20, "email": S, "years": "num"},
    "family": {"relation": 40, "name": S, "dob": "date", "gender": 2, "occupation": 80, "phone": 20, "dependant": "bool"},
}
LIST_MAX = 20


class Problem(Exception):
    pass


# ---------------------------------------------------------------- the link
def make_link(cand_id: str, nonce: str) -> str:
    now = int(time.time())
    return jwt.encode({"p": "candform", "sub": cand_id, "v": nonce, "iat": now, "exp": now + LINK_DAYS * 86400}, JWT_SECRET, algorithm="HS256")


def link_url(base: str, token: str) -> str:
    return f"{base.rstrip('/')}/#/apply?t={token}"


def link_mail(name: str, company: str, url: str) -> tuple[str, str]:
    subject = f"Your details for {company}"
    body = (f"Dear {name},\n\nThank you for your interest in {company}. Please fill in your details and attach your CV using this "
            f"link (it works for {LINK_DAYS} days):\n{url}\n\nYou can save the form and come back to it before you send it.\n")
    return subject, body


def open_candidate(conn, token: str) -> dict:
    """The candidate the link is for, while the link and the form are valid."""
    try:
        c = jwt.decode(token or "", JWT_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise Problem("This link has expired. Ask HR for a new one.") from None
    except jwt.PyJWTError:
        raise Problem("This link is not valid. Ask HR for a new one.") from None
    if c.get("p") != "candform" or not c.get("sub"):
        raise Problem("This link is not valid. Ask HR for a new one.")
    cand = repo.get_records(conn, "cands", [c["sub"]]).get(c["sub"])
    form = (cand or {}).get("form") or {}
    if not cand or form.get("nonce") != c.get("v"):
        raise Problem("This link is no longer valid. Ask HR for a new one.")
    return cand


def can_edit(cand: dict) -> bool:
    return ((cand.get("form") or {}).get("status")) in OPEN


def prefill(cand: dict) -> dict:
    """What the form starts with: what the candidate entered, or what HR already has."""
    data = (cand.get("form") or {}).get("data")
    if data:
        return data
    first, _, last = str(cand.get("name") or "").strip().partition(" ")
    return {"firstName": first, "lastName": last.strip(), "phone": cand.get("phone") or "", "gender": cand.get("gender") or "",
            "location": cand.get("location") or "", "currentCompany": cand.get("currentCompany") or "", "currentTitle": cand.get("currentTitle") or "",
            "expYears": cand.get("expYears") or "", "currentCtc": cand.get("currentCtc") or "", "expectedCtc": cand.get("expectedCtc") or "",
            "noticeDays": cand.get("noticeDays") or "", "skills": cand.get("skills") or "", "addrCountry": "India", "nationality": "Indian",
            "education": [], "prevJobs": [], "references": [], "family": []}


def public_view(conn, cand: dict) -> dict:
    co = repo.get_records(conn, "companies", [cand.get("companyId")]).get(cand.get("companyId")) or {}
    apps = repo.records_where(conn, "apps", "cand_id", cand["id"])
    reqs = repo.get_records(conn, "reqs", [a.get("reqId") for a in apps if a.get("reqId")])
    jobs = [reqs[a["reqId"]].get("title") for a in apps if a.get("reqId") in reqs and a.get("stage") not in ("rejected", "withdrawn")]
    form = cand.get("form") or {}
    cv = cand.get("cv") or {}
    return {"company": co.get("legalName") or co.get("name") or "", "name": cand.get("name") or "", "email": cand.get("email") or "",
            "jobs": [j for j in jobs if j], "status": form.get("status") or "sent", "note": form.get("note") or "",
            "editable": can_edit(cand), "submittedAt": form.get("submittedAt"), "data": prefill(cand),
            "cv": {"name": cv.get("name"), "size": cv.get("size")} if cv.get("name") else None}


# ---------------------------------------------------------------- what the candidate sends
def _value(v, kind):
    if kind == "bool":
        return bool(v)
    if kind == "num":
        if v in (None, ""):
            return ""
        try:
            n = float(str(v).replace(",", "").replace("₹", "").strip())
        except ValueError:
            raise Problem("Enter numbers with digits only.") from None
        if n < 0 or n > 1e10:
            raise Problem("A number is out of range.")
        return int(n) if n == int(n) else round(n, 2)
    v = "" if v is None else str(v)
    if kind == "date":
        v = v.strip()
        if v and not ISO.match(v):
            raise Problem("Enter dates as day, month and year.")
        return v
    if kind == "month":
        v = v.strip()
        if v and not YM.match(v):
            raise Problem("Enter the months of previous jobs as month and year.")
        return v
    v = v.replace("\r\n", "\n").strip()
    return v[:kind]


def clean(data: dict) -> dict:
    if not isinstance(data, dict):
        raise Problem("The form is not in the right form.")
    out = {k: _value(data.get(k), kind) for k, kind in FIELDS.items()}
    for name, spec in LISTS.items():
        rows = data.get(name) or []
        if not isinstance(rows, list):
            raise Problem("The form is not in the right form.")
        kept = []
        for r in rows[:LIST_MAX]:
            if not isinstance(r, dict):
                continue
            row = {k: _value(r.get(k), kind) for k, kind in spec.items()}
            if any(v not in ("", False) for v in row.values()):
                row["id"] = re.sub(r"[^A-Za-z0-9]", "", str(r.get("id") or ""))[:20] or uuid.uuid4().hex[:12]
                kept.append(row)
        out[name] = kept
    out["pan"] = out["pan"].upper().replace(" ", "")
    out["ifsc"] = out["ifsc"].upper().replace(" ", "")
    out["aadhaar"] = re.sub(r"\D", "", out["aadhaar"])
    out["uan"] = re.sub(r"\D", "", out["uan"])
    return out


def check(d: dict, submit: bool):
    """Formats are checked on every save; what must be there, when the form is sent."""
    today = date.today().isoformat()
    if d["pan"] and not PAN.match(d["pan"]):
        raise Problem("The PAN has 10 characters: 5 letters, 4 digits and a letter, for example ABCDE1234F.")
    if d["aadhaar"] and len(d["aadhaar"]) != 12:
        raise Problem("The Aadhaar number has 12 digits.")
    if d["uan"] and len(d["uan"]) != 12:
        raise Problem("The UAN has 12 digits. Leave it empty if you have never had one.")
    if d["ifsc"] and not IFSC.match(d["ifsc"]):
        raise Problem("The IFSC has 11 characters, the fifth a zero, for example HDFC0001234.")
    if d["addrCountry"] in ("", "India") and d["addrPin"] and not re.match(r"^[1-9]\d{5}$", d["addrPin"]):
        raise Problem("The PIN code has 6 digits and does not start with 0.")
    for k, label in (("phone", "your mobile number"), ("altPhone", "the other phone number"), ("emergencyPhone", "the emergency contact's phone")):
        if d[k] and not PHONE.match(d[k]):
            raise Problem(f"Enter {label} with digits only.")
    if d["dob"] and (d["dob"] > today or d["dob"] < "1940-01-01"):
        raise Problem("Check your date of birth.")
    for j in d["prevJobs"]:
        if j["to"] and j["from"] and j["to"] < j["from"]:
            raise Problem(f"The job at {j['employer'] or 'a previous employer'} ends before it starts.")
        if j["from"] and j["from"] > today[:7]:
            raise Problem(f"The job at {j['employer'] or 'a previous employer'} starts in the future.")
    for r in d["references"]:
        if r["email"] and not EMAIL.match(r["email"]):
            raise Problem(f"{r['email']} is not an e-mail address.")
    for e in d["education"]:
        if e["fromYear"] and e["toYear"] and e["toYear"] < e["fromYear"]:
            raise Problem(f"{e['qualification'] or 'A qualification'} is passed before it starts.")
    if not submit:
        return
    need = [("firstName", "your first name"), ("dob", "your date of birth"), ("gender", "your gender"), ("phone", "your mobile number"),
            ("address", "your address"), ("addrCity", "your city"), ("emergencyName", "an emergency contact"), ("emergencyPhone", "the emergency contact's phone")]
    for k, label in need:
        if not d[k]:
            raise Problem(f"Enter {label} before sending the form.")
    if not d["education"]:
        raise Problem("Add at least your highest qualification before sending the form.")
    for e in d["education"]:
        if not (e["qualification"] and e["institution"]):
            raise Problem("Give the qualification and the institution of each line under Education.")
    for j in d["prevJobs"]:
        if not (j["employer"] and j["designation"] and j["from"]):
            raise Problem("Give the employer, designation and start of each previous job.")
    for f in d["family"]:
        if not (f["relation"] and f["name"]):
            raise Problem("Give the relationship and name of each family member.")
    if not d["declaration"]:
        raise Problem("Tick the declaration that the details are true before sending.")


def clean_cv(cv) -> dict | None:
    if not cv:
        return None
    if not isinstance(cv, dict):
        raise Problem("The CV could not be read.")
    data, mime = str(cv.get("data") or ""), str(cv.get("type") or "").lower()
    m = re.match(r"^data:([\w.+/-]+);base64,(.+)$", data, re.S)
    if not m:
        raise Problem("The CV could not be read. Attach it again.")
    mime = mime or m.group(1).lower()
    if mime not in CV_MIME or m.group(1).lower() not in CV_MIME:
        raise Problem("Attach the CV as a PDF, Word, RTF or text file.")
    try:
        raw = base64.b64decode(m.group(2), validate=False)
    except ValueError:
        raise Problem("The CV could not be read. Attach it again.") from None
    if len(raw) > CV_MAX:
        raise Problem("The CV is larger than 2 MB.")
    name = re.sub(r"[\\/:*?\"<>|]+", "_", str(cv.get("name") or "CV"))[-120:]
    return {"name": name, "type": mime, "size": len(raw), "data": data, "at": int(time.time() * 1000), "byCandidate": True}


def save(conn, cand: dict, data: dict, cv, submit: bool) -> dict:
    if not can_edit(cand):
        raise Problem("This form has already been sent. Ask HR if something needs to change.")
    d = clean(data)
    check(d, submit)
    now = int(time.time() * 1000)
    form = dict(cand.get("form") or {})
    form.update({"data": d, "savedAt": now, "status": "submitted" if submit else "draft"})
    if submit:
        form["submittedAt"] = now
        form["note"] = ""
        form["log"] = [*(form.get("log") or [])[-30:], {"at": now, "what": "Sent by the candidate"}]
    rec = {**cand, "form": form}
    new_cv = clean_cv(cv)
    if new_cv:
        rec["cv"] = new_cv
    if submit:
        # what HR shows in the candidate pool follows what the candidate says about themselves
        name = " ".join(x for x in (d["firstName"], d["lastName"]) if x)
        for k, v in (("name", name), ("phone", d["phone"]), ("gender", d["gender"]), ("location", d["addrCity"] or d["location"]),
                     ("currentCompany", d["currentCompany"]), ("currentTitle", d["currentTitle"]), ("expYears", d["expYears"]),
                     ("currentCtc", d["currentCtc"]), ("expectedCtc", d["expectedCtc"]), ("noticeDays", d["noticeDays"]), ("skills", d["skills"])):
            if v not in ("", None):
                rec[k] = v
    repo.upsert(conn, "cands", [rec], None)
    repo.audit_add(conn, "Candidate sent their application form" if submit else "Candidate saved their application form", rec.get("name") or "", None,
                   module="recruitment", ref_type="candidate", ref_id=rec["id"])
    repo.bump_rev(conn)
    return rec


# ---------------------------------------------------------------- HR's link, and saves from the app
def start(cand: dict, by: str) -> tuple[dict, str]:
    """A new link: older links stop working. A form already sent is opened again for changes."""
    form = dict(cand.get("form") or {})
    if form.get("status") == "closed":
        raise Problem("This candidate has joined; their details are on their employee record now.")
    nonce = uuid.uuid4().hex[:16]
    now = int(time.time() * 1000)
    st = form.get("status")
    form.update({"nonce": nonce, "sentAt": now, "sentBy": by,
                 "status": "returned" if st == "submitted" else st if st in ("draft", "returned") else "sent"})
    form["log"] = [*(form.get("log") or [])[-30:], {"at": now, "by": by, "what": "Link sent"}]
    return {**cand, "form": form}, nonce


KEEP = ("data", "savedAt", "submittedAt", "nonce", "sentAt", "sentBy")


def merge_from_app(new: dict, old: dict | None, me: str) -> dict:
    """A candidate saved from the app: the form as stored, except that HR may return it for changes or close it."""
    of = (old or {}).get("form")
    nf = new.get("form")
    if not of:
        new.pop("form", None)
        return new
    out = dict(of)
    if isinstance(nf, dict):
        st = nf.get("status")
        if st != of.get("status"):
            if st == "returned" and of.get("status") == "submitted":
                out["status"], out["note"] = "returned", str(nf.get("note") or "")[:600]
            elif st == "closed":
                out["status"] = "closed"
            else:
                st = None            # an older copy in the app: what the candidate did since stands
            if st:
                out["log"] = [*(of.get("log") or [])[-30:], {"at": int(time.time() * 1000), "by": me, "what": "Returned for changes" if st == "returned" else "Closed"}]
    for k in KEEP:
        if k in of:
            out[k] = of[k]
    new["form"] = out
    ocv, ncv = (old or {}).get("cv") or {}, new.get("cv") or {}
    if ocv.get("byCandidate") and (ncv.get("at") or 0) < (ocv.get("at") or 0):
        new["cv"] = ocv              # the copy in the app is older than the CV the candidate attached
    return new


def redact(cand: dict) -> dict:
    """Outside HR: whether the form was sent, not what is in it."""
    f = cand.get("form")
    if isinstance(f, dict):
        cand["form"] = {k: f.get(k) for k in ("status", "sentAt", "submittedAt") if k in f}
    return cand
