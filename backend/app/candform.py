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

2.12: the form offers the company's lists (employers, designations, responsibilities) as drop-downs with "Others",
previous jobs carry main and secondary responsibilities, and the candidate rates their level on each skill the
requisitions they are in need. When the form is sent, their levels are kept as `selfLevels` and, on requisitions
that shortlist automatically, a sourced candidate who matches well enough moves to Screening.

2.17: the candidate signs in. HR's link no longer opens the form by itself: on the first visit the candidate creates
a candidate sign-in (their e-mail address or mobile number, and a password of their own), and after that signs in,
from the link or from the sign-in page, to fill in, save and send the form. The form is read and written only with a
candidate's session (session subject "cd:" and the candidate id), so it is filled by the candidate: not by someone
who merely has the link, and not by an employee (an employee's session is refused, and a candidate sign-in cannot be
made for an active employee's e-mail address). Candidates' passwords are kept in `candidate_credentials`, apart from
the candidate record. A link sets a password once; a newer link from HR lets the candidate set a new one, which is
how a forgotten password is reset.

2.14: the form also asks for awards, and starts from the employment history, education and awards HR recorded on the
candidate. When it is sent, those lists on the candidate become what the candidate sent (HR's links to the standard
lists are kept on the rows the candidate did not remove). The e-mail names the jobs the candidate is invited for.
"""
import base64
import re
import time
import uuid
from datetime import date

import jwt
from sqlalchemy import text

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
                 "lastCtc": "num", "reason": 300, "duties": L, "contact": 200, "mainResp": "ids", "secResp": "ids"},
    "references": {"name": S, "organisation": S, "designation": S, "relation": 200, "phone": 20, "email": S, "years": "num"},
    "family": {"relation": 40, "name": S, "dob": "date", "gender": 2, "occupation": 80, "phone": 20, "dependant": "bool"},
    "awards": {"title": S, "issuer": S, "date": "date", "category": 20, "description": 600},
}
# 2.14: the lists HR may record on the candidate, and that the candidate's form starts from
HIST = ("prevJobs", "education", "awards")
LIST_MAX = 20
# 2.15: the standard reasons for leaving a job (the same list as LEAVE_REASONS in the app); "Others" lets them type one
LEAVE_REASONS = ("Better role or career growth", "Higher pay", "Relocation", "Contract or project ended", "Company closed, downsized or layoff",
                 "Higher studies", "Family or personal reasons", "Health reasons", "Better work-life balance", "Retirement",
                 "Asked to leave by the employer", "Still working there")
IDS_MAX = 40
ID = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
LEVELS = {0: "None", 1: "Basic", 2: "Working", 3: "Advanced", 4: "Expert"}
SHORTLIST_STAGE = "screening"


class Problem(Exception):
    pass


# ---------------------------------------------------------------- 2.17: the candidate's sign-in
SESSION_PREFIX = "cd:"             # session subject of a candidate
PW_MIN, PW_MAX = 10, 200
CRED_DDL = """CREATE TABLE IF NOT EXISTS candidate_credentials (
  cand_id     VARCHAR(64)  NOT NULL PRIMARY KEY,
  pw_hash     VARCHAR(100) NULL,
  set_with    VARCHAR(32)  NULL,
  last_login  BIGINT       NULL,
  updated_at  TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""


def _phone10(v) -> str:
    d = re.sub(r"\D", "", str(v or ""))
    return d[-10:] if len(d) >= 10 else ""


def get_cred(conn, cand_id: str) -> dict:
    r = conn.execute(text("SELECT pw_hash, set_with, last_login FROM candidate_credentials WHERE cand_id=:i"), {"i": cand_id}).first()
    return {"pw": r[0], "setWith": r[1], "lastLogin": r[2]} if r else {"pw": None, "setWith": None, "lastLogin": None}


def set_cred(conn, cand_id: str, pw_hash: str, nonce: str):
    conn.execute(text("INSERT INTO candidate_credentials (cand_id, pw_hash, set_with) VALUES (:i, :h, :n) "
                      "ON DUPLICATE KEY UPDATE pw_hash=VALUES(pw_hash), set_with=VALUES(set_with)"),
                 {"i": cand_id, "h": pw_hash, "n": nonce})


def note_login(conn, cand_id: str):
    conn.execute(text("UPDATE candidate_credentials SET last_login=:t WHERE cand_id=:i"), {"t": int(time.time() * 1000), "i": cand_id})


def login_name(cand: dict) -> str:
    """What the candidate signs in with: their e-mail address, or their mobile number if HR has no e-mail."""
    return (cand.get("email") or "").strip() or (cand.get("phone") or "").strip()


def candidates_for_login(conn, login: str) -> list:
    """The candidates with a sign-in whose e-mail address (or mobile number) this is, newest first. The same person
    may be a candidate in more than one company of the group; each has its own record and password."""
    login = (login or "").strip()
    with_pw = [r[0] for r in conn.execute(text("SELECT cand_id FROM candidate_credentials WHERE pw_hash IS NOT NULL"))]
    if not with_pw or not login:
        return []
    if "@" in login:
        q = text("SELECT data FROM candidates WHERE email=:e AND id IN :ids ORDER BY updated_at DESC").bindparams(repo._expanding("ids"))
        return [repo.loads(d) for d in conn.execute(q, {"e": login.lower(), "ids": with_pw}).scalars()]
    ph = _phone10(login)
    if not ph:
        return []
    out = []
    for cid, c in repo.get_records(conn, "cands", with_pw).items():
        if not (c.get("email") or "").strip() and _phone10(c.get("phone")) == ph:
            out.append(c)
    return out


def session_problem(cand: dict | None, cred: dict) -> str:
    """Why a candidate may not be signed in, or ''."""
    if not cand or not cred.get("pw"):
        return "This account is not active. Ask HR for a new link."
    if ((cand.get("form") or {}).get("status")) == "closed":
        return "You have joined the company, so your details are on your employee record now. Sign in as an employee."
    if not (cand.get("form") or {}).get("nonce"):
        return "HR has not asked you to fill in your details yet."
    return ""


# ---------------------------------------------------------------- the link
def make_link(cand_id: str, nonce: str) -> str:
    now = int(time.time())
    return jwt.encode({"p": "candform", "sub": cand_id, "v": nonce, "iat": now, "exp": now + LINK_DAYS * 86400}, JWT_SECRET, algorithm="HS256")


def link_url(base: str, token: str) -> str:
    return f"{base.rstrip('/')}/#/apply?t={token}"




def job_titles(conn, cand: dict) -> list:
    """The titles of the live requisitions the candidate is in."""
    apps = repo.records_where(conn, "apps", "cand_id", cand["id"])
    reqs = repo.get_records(conn, "reqs", [a.get("reqId") for a in apps if a.get("reqId")])
    out = []
    for a in apps:
        t = (reqs.get(a.get("reqId")) or {}).get("title")
        if t and a.get("stage") not in ("rejected", "withdrawn") and t not in out:
            out.append(t)
    return out


def open_candidate(conn, token: str) -> dict:
    return read_link(conn, token)[0]


def read_link(conn, token: str) -> tuple[dict, str]:
    """(candidate, nonce) for a link, while the link is valid: the latest one HR sent, within 14 days."""
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
    return cand, c["v"]


def link_view(conn, cand: dict, nonce: str, cred: dict) -> dict:
    """What the link page shows before sign-in: whose link it is and whether to create a sign-in or sign in.
    Nothing the candidate entered is shown here."""
    co = repo.get_records(conn, "companies", [cand.get("companyId")]).get(cand.get("companyId")) or {}
    form = cand.get("form") or {}
    return {"company": co.get("legalName") or co.get("name") or "", "name": cand.get("name") or "",
            "login": login_name(cand), "jobs": job_titles(conn, cand), "hasAccount": bool(cred.get("pw")),
            # a link sets a password once; HR's newer link lets the candidate set a new one
            "canSetPassword": cred.get("setWith") != nonce,
            "closed": form.get("status") == "closed"}


def account_problem(conn, cand: dict) -> str:
    """Why a candidate sign-in may not be made for this candidate, or ''."""
    if ((cand.get("form") or {}).get("status")) == "closed":
        return "You have joined the company, so your details are on your employee record now. Sign in as an employee."
    who = login_name(cand)
    if not who:
        return "HR has no e-mail address or mobile number for you. Ask HR to add one and send the link again."
    if is_employee_login(conn, cand):
        return ("This e-mail address belongs to an employee of the company. The candidate form is filled in by candidates, "
                "not employees. If you are an employee, speak to HR.")
    return ""


def is_employee_login(conn, cand: dict) -> bool:
    """Whether the candidate's e-mail address is an active employee's sign-in."""
    email = (cand.get("email") or "").strip().lower()
    if not email:
        return False
    return bool(conn.execute(text("SELECT 1 FROM employees WHERE email=:e AND (status IS NULL OR status<>'exited') LIMIT 1"),
                             {"e": email}).scalar())


def note_account(conn, cand: dict, first: bool) -> dict:
    """Records on the candidate, for HR, that they made (or reset) their sign-in."""
    now = int(time.time() * 1000)
    form = dict(cand.get("form") or {})
    form["accountAt"] = form.get("accountAt") or now
    form["log"] = [*(form.get("log") or [])[-30:], {"at": now, "what": "Candidate created their sign-in" if first else "Candidate set a new password"}]
    rec = {**cand, "form": form}
    repo.upsert(conn, "cands", [rec], None)
    repo.bump_rev(conn)
    return rec


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
            "references": [], "family": [], **{k: _hist_rows(cand.get(k), LISTS[k]) for k in HIST}}


def _hist_rows(rows, spec: dict) -> list:
    """HR's rows, in the form's shape."""
    out = []
    for r in (rows or [])[:LIST_MAX]:
        if isinstance(r, dict):
            row = {k: (r.get(k) if r.get(k) is not None else ([] if kind == "ids" else False if kind == "bool" else "")) for k, kind in spec.items()}
            row["id"] = re.sub(r"[^A-Za-z0-9]", "", str(r.get("id") or ""))[:20]
            out.append(row)
    return out


def public_view(conn, cand: dict) -> dict:
    co = repo.get_records(conn, "companies", [cand.get("companyId")]).get(cand.get("companyId")) or {}
    jobs = job_titles(conn, cand)
    form = cand.get("form") or {}
    cv = cand.get("cv") or {}
    return {"company": co.get("legalName") or co.get("name") or "", "name": cand.get("name") or "", "email": cand.get("email") or "",
            "jobs": [j for j in jobs if j], "status": form.get("status") or "sent", "note": form.get("note") or "",
            "editable": can_edit(cand), "submittedAt": form.get("submittedAt"), "data": prefill(cand),
            "cv": {"name": cv.get("name"), "size": cv.get("size")} if cv.get("name") else None,
            "skills": wanted_skills(conn, cand), "levels": LEVELS, "lists": lists_for(conn, cand.get("companyId")),
            "rules": {k: {"req": r["req"], "max": r["max"]} for k, r in form_rules(conn, cand.get("companyId")).items()}}


# ---------------------------------------------------------------- what the candidate sends
def _value(v, kind):
    if kind == "bool":
        return bool(v)
    if kind == "ids":
        if not isinstance(v, list):
            return []
        out = []
        for x in v[:IDS_MAX]:
            x = str(x or "")
            if ID.match(x) and x not in out:
                out.append(x)
        return out
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
            if any(v not in ("", False, []) for v in row.values()):
                row["id"] = re.sub(r"[^A-Za-z0-9]", "", str(r.get("id") or ""))[:20] or uuid.uuid4().hex[:12]
                kept.append(row)
        out[name] = kept
    for j in out["prevJobs"]:
        j["secResp"] = [x for x in j["secResp"] if x not in j["mainResp"]]     # main wins if both
    out["skillLevels"] = _levels(data.get("skillLevels"))
    out["pan"] = out["pan"].upper().replace(" ", "")
    out["ifsc"] = out["ifsc"].upper().replace(" ", "")
    out["aadhaar"] = re.sub(r"\D", "", out["aadhaar"])
    out["uan"] = re.sub(r"\D", "", out["uan"])
    return out


def _levels(v) -> dict:
    """{skill id: 0..4}; anything else is dropped."""
    if not isinstance(v, dict):
        return {}
    out = {}
    for k, x in list(v.items())[:100]:
        if not ID.match(str(k)) or x in ("", None):
            continue
        try:
            n = int(x)
        except (TypeError, ValueError):
            continue
        if n in LEVELS:
            out[str(k)] = n
    return out


# ---------------------------------------------------------------- 2.12: lists, skills and the match
def _req_skills(req: dict) -> list:
    out = []
    for need in ("primary", "secondary"):
        for x in req.get(need + "Skills") or []:
            if isinstance(x, dict) and x.get("skillId"):
                out.append({"skillId": x["skillId"], "level": x.get("level"), "need": need})
    return out


def wanted_skills(conn, cand: dict) -> list:
    """The skills the candidate's live requisitions need: [{id, name, need}], primary first."""
    apps = [a for a in repo.records_where(conn, "apps", "cand_id", cand["id"]) if a.get("stage") not in ("rejected", "withdrawn", "joined")]
    reqs = repo.get_records(conn, "reqs", [a.get("reqId") for a in apps])
    need = {}
    for r in reqs.values():
        for s in _req_skills(r):
            if need.get(s["skillId"]) != "primary":
                need[s["skillId"]] = s["need"]
    items = repo.get_records(conn, "masterItems", list(need))
    out = [{"id": i, "name": (items.get(i) or {}).get("name") or "", "need": n} for i, n in need.items()
           if (items.get(i) or {}).get("kind") == "skill" and (items[i].get("status") in ("approved", "proposed"))]
    return sorted(out, key=lambda x: (x["need"] != "primary", x["name"].lower()))


def lists_for(conn, company_id: str) -> dict:
    """What the drop-downs on the form offer: the company's employers, designations and responsibilities."""
    items = [x for x in repo.records_where(conn, "masterItems", "company_id", company_id) if x.get("status") == "approved"]
    by = lambda kind: sorted((x for x in items if x.get("kind") == kind), key=lambda x: str(x.get("name") or "").lower())
    desigs = sorted({str(d.get("name") or "").strip() for d in repo.records_where(conn, "desigs", "company_id", company_id)} - {""}, key=str.lower)
    cities = sorted({str(x.get("name") or "").strip() for x in repo.records_where(conn, "locations", "company_id", company_id)} - {""}, key=str.lower)
    return {"employers": [x["name"] for x in by("employer")], "designations": desigs, "cities": cities, "leaveReasons": list(LEAVE_REASONS),
            "responsibilities": [{"id": x["id"], "name": x["name"], "category": x.get("category") or ""} for x in by("responsibility")]}


def level_of(cand: dict, skill_id: str):
    """HR's assessed level counts; otherwise the candidate's own rating; None when neither."""
    for src in (cand.get("skillLevels") or {}, cand.get("selfLevels") or {}, ((cand.get("form") or {}).get("data") or {}).get("skillLevels") or {}):
        v = src.get(skill_id)
        if v not in (None, ""):
            try:
                return int(v)
            except (TypeError, ValueError):
                return None
    return None


def skill_match(cand: dict, req: dict):
    """Same rule as skillMatch() in the app: primary skills count twice, each scores min(level / needed, 1)."""
    need = _req_skills(req)
    if not need:
        return None
    got = tot = 0.0
    unrated, primary_ok = 0, True
    for n in need:
        w = 2 if n["need"] == "primary" else 1
        try:
            want = max(1, int(n.get("level") or 1))
        except (TypeError, ValueError):
            want = 1
        have = level_of(cand, n["skillId"])
        if have is None:
            unrated += 1
        tot += w
        got += w * min((have or 0) / want, 1)
        if (have or 0) < want and n["need"] == "primary":
            primary_ok = False
    return {"pct": round(got / tot * 100), "unrated": unrated, "primaryOk": primary_ok}


def meets_shortlist(m, req: dict) -> bool:
    if not m or m["unrated"]:
        return False
    try:
        floor = 70 if req.get("matchMin") in (None, "") else float(req["matchMin"])
    except (TypeError, ValueError):
        floor = 70
    return m["pct"] >= floor and (req.get("primaryMust") is False or m["primaryOk"])


def auto_shortlist(conn, cand: dict) -> int:
    """Sourced applications of this candidate move to Screening on requisitions that shortlist automatically."""
    apps = [a for a in repo.records_where(conn, "apps", "cand_id", cand["id"]) if a.get("stage") == "sourced"]
    reqs = repo.get_records(conn, "reqs", [a.get("reqId") for a in apps])
    now = int(time.time() * 1000)
    moved = []
    for a in apps:
        r = reqs.get(a.get("reqId")) or {}
        if not r.get("autoShortlist") or r.get("status") != "open":
            continue
        m = skill_match(cand, r)
        if not meets_shortlist(m, r):
            continue
        note = f"Shortlisted automatically: skills match {m['pct']}%"
        moved.append({**a, "stage": SHORTLIST_STAGE, "stageAt": now, "autoShortlisted": True,
                      "history": [*(a.get("history") or []), {"stage": SHORTLIST_STAGE, "at": now, "by": "", "note": note}]})
    if moved:
        repo.upsert(conn, "apps", moved, None)
        for a in moved:
            repo.audit_add(conn, "Candidate shortlisted by skills match", f"{cand.get('name') or ''}: {(reqs.get(a.get('reqId')) or {}).get('no') or ''}", None,
                           module="recruitment", ref_type="candidate", ref_id=cand["id"])
    return len(moved)


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
    for a in d["awards"]:
        if a["date"] and a["date"] > today:
            raise Problem(f"The date of {a['title'] or 'an award'} is in the future.")
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
    for a in d["awards"]:
        if not a["title"]:
            raise Problem("Give the name of each award under Awards.")
    if not d["declaration"]:
        raise Problem("Tick the declaration that the details are true before sending.")


def form_rules(conn, company_id: str) -> dict:
    """2.13: HR's field settings for the candidate's form: {field: {req, max, label}}, top-level fields only."""
    co = repo.get_records(conn, "companies", [company_id]).get(company_id) or {}
    rules = ((co.get("fieldRules") or {}).get("candform") or {})
    out = {}
    for k, r in rules.items():
        if k in FIELDS and isinstance(r, dict) and FIELDS[k] not in ("bool",):
            try:
                mx = int(r.get("max") or 0)
            except (TypeError, ValueError):
                mx = 0
            out[k] = {"req": bool(r.get("req")), "max": max(0, min(mx, 2000)), "label": str(r.get("label") or k)[:80]}
    return out


def apply_rules(d: dict, rules: dict, submit: bool):
    """Text is cut to HR's longest entry on every save; required fields are checked when the form is sent."""
    for k, r in rules.items():
        if r["max"] and isinstance(d.get(k), str):
            d[k] = d[k][:r["max"]]
    if submit:
        for k, r in rules.items():
            if r["req"] and d.get(k) in ("", None):
                lb = r["label"]
                first = lb.split(" ")[0]
                lb = lb[:1].lower() + lb[1:] if first[1:].islower() else lb   # "Mobile number" -> "mobile number"; keep LinkedIn, PAN, UAN as written
                raise Problem(f"Enter {lb} before sending the form.")


def check_skills(d: dict, wanted: list, submit: bool):
    """Only the skills asked about are kept; when the form is sent, each must have a level (None is a level)."""
    ids = {s["id"] for s in wanted}
    d["skillLevels"] = {k: v for k, v in d["skillLevels"].items() if k in ids}
    if submit:
        missing = [s["name"] for s in wanted if s["id"] not in d["skillLevels"]]
        if missing:
            raise Problem(f"Choose your level in {', '.join(missing[:3])}{' and others' if len(missing) > 3 else ''} under Your skills (None if you do not have it).")


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
    check_skills(d, wanted_skills(conn, cand), submit)
    apply_rules(d, form_rules(conn, cand.get("companyId")), submit)
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
        rec["selfLevels"] = dict(d["skillLevels"])
        # 2.14: the candidate's history replaces HR's; links HR made to the standard lists stay on the rows kept
        for k in HIST:
            old = {str(x.get("id")): x for x in (cand.get(k) or []) if isinstance(x, dict) and x.get("id")}
            rec[k] = [{**{kk: vv for kk, vv in old.get(r["id"], {}).items() if kk not in LISTS[k] and kk != "verify"}, **r} for r in d[k]]
    repo.upsert(conn, "cands", [rec], None)
    if submit:
        auto_shortlist(conn, rec)
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


KEEP = ("data", "savedAt", "submittedAt", "nonce", "sentAt", "sentBy", "accountAt")


def merge_from_app(new: dict, old: dict | None, me: str) -> dict:
    """A candidate saved from the app: the form as stored, except that HR may return it for changes or close it."""
    of = (old or {}).get("form")
    nf = new.get("form")
    # the candidate's own skill ratings are written only here, from their form
    if (old or {}).get("selfLevels") is not None:
        new["selfLevels"] = old["selfLevels"]
    else:
        new.pop("selfLevels", None)
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
