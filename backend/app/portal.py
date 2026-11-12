"""
PeopleDesk 2.9: contractor portal and access links.

- A contractor (the agency that supplies contract workers) has portal users, kept on the contractor record by HR
  (`portalUsers`). A portal user signs in to a separate, small part of PeopleDesk: they see their own contractor
  and its workers, and nothing else of the company.
- A portal user adds workers. Each becomes an employee record in the company: category "contract", attached to
  this contractor for good (only HR can move a worker to another contractor). A worker engaged through one
  contractor cannot be added again by another while they are active.
- A worker, or a portal user, gets in through an access link: a signed link, valid for 7 days and only until a
  password is set with it. Contract workers and portal users rarely have a company Google or Microsoft account, so
  they sign in with their e-mail or mobile number and a password, even where passwords are off for staff.
- Portal passwords are kept in their own table (`contractor_credentials`), apart from the contractor record.
"""
import hashlib
import re
import time
import uuid
from datetime import date

import jwt
from sqlalchemy import text

from . import repo, workforce
from .config import JWT_SECRET

PORTAL_PREFIX = "cu:"               # session subject of a contractor portal user
INVITE_DAYS = 7
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")

CRED_DDL = """CREATE TABLE IF NOT EXISTS contractor_credentials (
  user_id       VARCHAR(64)  NOT NULL PRIMARY KEY,
  contractor_id VARCHAR(64)  NOT NULL,
  pw_hash       VARCHAR(100) NULL,
  last_login    BIGINT       NULL,
  updated_at    TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  KEY ix_contractor (contractor_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""

# What a contractor enters for a new worker. Everything else (statutory numbers, bank, family, background) the
# worker enters, or HR sets (salary, reporting, grade).
WORKER_FIELDS = ("firstName", "lastName", "gender", "dob", "phone", "email", "doj", "deptId", "desigId", "locationId", "shiftId")


class Problem(Exception):
    pass


def phone10(v) -> str:
    """The last 10 digits of an Indian mobile number, which is how people type it."""
    d = re.sub(r"\D", "", str(v or ""))
    return d[-10:] if len(d) >= 10 else ""


def _clean(v, n=120) -> str:
    return " ".join(str(v or "").split())[:n]


# ---------------------------------------------------------------- reading
def all_contractors(conn) -> list:
    return [repo.loads(d) for d in conn.execute(text("SELECT data FROM contractors")).scalars()]


def portal_users(con: dict) -> list:
    return [u for u in (con.get("portalUsers") or []) if isinstance(u, dict) and u.get("id")]


def is_open(con: dict | None, user: dict | None) -> bool:
    return bool(con) and bool(user) and con.get("active") is not False and user.get("active") is not False


def find_user_by_login(conn, login: str):
    """(contractor, portal user) for an e-mail address or mobile number, or (None, None)."""
    login = (login or "").strip().lower()
    ph = "" if "@" in login else phone10(login)
    for con in all_contractors(conn):
        for u in portal_users(con):
            if ("@" in login and (u.get("email") or "").strip().lower() == login) or (ph and phone10(u.get("phone")) == ph):
                return con, u
    return None, None


def get_user(conn, user_id: str):
    for con in all_contractors(conn):
        for u in portal_users(con):
            if u["id"] == user_id:
                return con, u
    return None, None


def find_employee_by_phone(conn, login: str):
    """An active employee whose mobile number is this one, if exactly one has it."""
    ph = phone10(login)
    if not ph or "@" in (login or ""):
        return None
    hits = [e for e in repo.employees_index(conn).values() if e.get("status") != "exited" and phone10(e.get("phone")) == ph]
    return hits[0] if len(hits) == 1 else None


def get_pw(conn, user_id: str):
    return conn.execute(text("SELECT pw_hash FROM contractor_credentials WHERE user_id=:i"), {"i": user_id}).scalar()


def set_pw(conn, user_id: str, contractor_id: str, h: str):
    conn.execute(text("INSERT INTO contractor_credentials (user_id, contractor_id, pw_hash) VALUES (:i, :c, :h) "
                      "ON DUPLICATE KEY UPDATE pw_hash=VALUES(pw_hash), contractor_id=VALUES(contractor_id)"),
                 {"i": user_id, "c": contractor_id, "h": h})


def note_login(conn, user_id: str):
    conn.execute(text("UPDATE contractor_credentials SET last_login=:t WHERE user_id=:i"), {"t": int(time.time() * 1000), "i": user_id})


def employees_with_access(conn, ids) -> set:
    ids = [i for i in ids if i]
    if not ids:
        return set()
    q = text("SELECT employee_id FROM auth_credentials WHERE employee_id IN :ids AND (pw_hash IS NOT NULL OR google_sub IS NOT NULL)")
    return {r[0] for r in conn.execute(q.bindparams(repo._expanding("ids")), {"ids": ids})}


def portal_users_with_access(conn, ids) -> dict:
    ids = [i for i in ids if i]
    if not ids:
        return {}
    q = text("SELECT user_id, last_login FROM contractor_credentials WHERE user_id IN :ids AND pw_hash IS NOT NULL")
    return {r[0]: r[1] for r in conn.execute(q.bindparams(repo._expanding("ids")), {"ids": ids})}


# ---------------------------------------------------------------- access links
def _fingerprint(pw_hash) -> str:
    return hashlib.sha256((pw_hash or "-").encode()).hexdigest()[:16]


def make_invite(kind: str, sub: str, pw_hash) -> str:
    """kind: 'emp' (an employee, a contract worker included) or 'con' (a contractor portal user). The link stops
    working once a password is set with it, because the fingerprint of the stored password changes."""
    now = int(time.time())
    return jwt.encode({"p": "invite", "k": kind, "sub": sub, "v": _fingerprint(pw_hash), "iat": now, "exp": now + INVITE_DAYS * 86400},
                      JWT_SECRET, algorithm="HS256")


def read_invite(token: str) -> dict:
    try:
        c = jwt.decode(token or "", JWT_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise Problem("This link has expired. Ask for a new one.") from None
    except jwt.PyJWTError:
        raise Problem("This link is not valid. Ask for a new one.") from None
    if c.get("p") != "invite" or c.get("k") not in ("emp", "con") or not c.get("sub"):
        raise Problem("This link is not valid. Ask for a new one.")
    return c


def invite_still_valid(claims: dict, pw_hash) -> None:
    if claims.get("v") != _fingerprint(pw_hash):
        raise Problem("This link was already used. Sign in with your password, or ask for a new link.")


def invite_url(base: str, token: str) -> str:
    return f"{base.rstrip('/')}/#/welcome?t={token}"


# ---------------------------------------------------------------- HR saving a contractor
def check_contractor(conn, new: dict, old: dict | None) -> dict:
    """Portal users on a contractor HR saves: names and e-mails tidied, and each e-mail or mobile number belongs to
    one person only (not an employee, not another portal user), so sign-in finds the right account."""
    users = new.get("portalUsers")
    if users is None:
        return new
    if not isinstance(users, list):
        raise Problem("portal users are not in the right form")
    emps = repo.employees_index(conn)
    emp_mail = {(e.get("email") or "").lower() for e in emps.values() if e.get("email")}
    emp_phone = {phone10(e.get("phone")) for e in emps.values() if e.get("status") != "exited"} - {""}
    others = [u for c in all_contractors(conn) if c.get("id") != new.get("id") for u in portal_users(c)]
    seen_mail, seen_phone, out = set(), set(), []
    for u in users:
        if not isinstance(u, dict):
            continue
        u = {**u, "id": str(u.get("id") or uuid.uuid4().hex[:14]), "name": _clean(u.get("name")), "email": (u.get("email") or "").strip().lower(),
             "phone": _clean(u.get("phone"), 20)}
        if not u["name"]:
            raise Problem("give each portal user's name")
        if u["email"] and not EMAIL.match(u["email"]):
            raise Problem(f"{u['email']} is not an e-mail address")
        if not u["email"] and not phone10(u["phone"]):
            raise Problem(f"{u['name']} needs an e-mail address or a mobile number to sign in with")
        if u["email"] and (u["email"] in emp_mail or u["email"] in seen_mail or any((o.get("email") or "").lower() == u["email"] for o in others)):
            raise Problem(f"{u['email']} is already used by someone else in PeopleDesk")
        ph = phone10(u["phone"])
        if ph and (ph in emp_phone or ph in seen_phone or any(phone10(o.get("phone")) == ph for o in others)):
            raise Problem(f"the mobile number of {u['name']} is already used by someone else in PeopleDesk")
        seen_mail.add(u["email"])
        seen_phone.add(ph)
        out.append(u)
    return {**new, "portalUsers": out}


# ---------------------------------------------------------------- what a portal user sees
def _named(conn, coll: str, company_id: str, keys=("id", "name")) -> list:
    rows = repo.records_where(conn, coll, "company_id", company_id)
    return sorted(({k: r.get(k) for k in keys} for r in rows if r.get("active") is not False), key=lambda x: str(x.get("name") or ""))


def details_done(e: dict) -> dict:
    """Which parts of their profile a worker has filled in (yes or no only: the contractor does not see the
    numbers themselves)."""
    return {
        "personal": bool(e.get("dob") and e.get("gender") and e.get("address") and (e.get("emergencyPhone") or e.get("emergency"))),
        "family": bool(e.get("family")),
        "background": bool(e.get("education") or e.get("prevJobs")),
        "statutory": bool(e.get("aadhaar") or e.get("uan") or e.get("pan")),
        "bank": bool(e.get("bankAcc") and e.get("ifsc")),
    }


def workers_of(conn, con: dict) -> list:
    return [e for e in repo.records_where(conn, "employees", "company_id", con.get("companyId"))
            if e.get("contractorId") == con.get("id") and workforce.register_of(e) == "contract"]


def worker_view(e: dict, has_access: bool) -> dict:
    out = {k: e.get(k) for k in ("id", "empNo", *WORKER_FIELDS, "status")}
    out["lwd"] = (e.get("exit") or {}).get("lwd") or ""
    out["access"] = "active" if has_access else ("link" if e.get("accessLinkAt") else "none")
    out["accessLinkAt"] = e.get("accessLinkAt")
    out["editable"] = not has_access and e.get("status") == "active"
    out["details"] = details_done(e)
    out["addedBy"] = (e.get("addedBy") or {}).get("name", "")
    return out


def state(conn, con: dict, user: dict, mail_ok: bool) -> dict:
    co = repo.get_records(conn, "companies", [con.get("companyId")]).get(con.get("companyId")) or {}
    ws = workers_of(conn, con)
    access = employees_with_access(conn, [w["id"] for w in ws])
    shifts = repo.records_where(conn, "shifts", "company_id", con.get("companyId"))
    return {
        "user": {k: user.get(k) for k in ("id", "name", "email", "phone")},
        "contractor": {k: con.get(k) for k in ("id", "name", "code", "licenceNo", "licenceTo", "maxWorkers")},
        "company": {"id": co.get("id"), "name": co.get("legalName") or co.get("name"), "code": co.get("code")},
        "masters": {
            "depts": _named(conn, "depts", con.get("companyId")),
            "desigs": _named(conn, "desigs", con.get("companyId")),
            "locations": _named(conn, "locations", con.get("companyId")),
            "shifts": sorted(({"id": s.get("id"), "name": s.get("name"), "start": s.get("start"), "end": s.get("end")} for s in shifts), key=lambda x: str(x["name"] or "")),
        },
        "workers": sorted((worker_view(e, e["id"] in access) for e in ws), key=lambda w: (w["status"] == "exited", f"{w.get('firstName') or ''} {w.get('lastName') or ''}".lower())),
        "mail": mail_ok,
    }


# ---------------------------------------------------------------- adding and correcting workers
def _check_worker(conn, con: dict, d: dict, emp_id: str | None) -> dict:
    out = {k: _clean(d.get(k)) for k in WORKER_FIELDS}
    out["email"] = out["email"].lower()
    if not out["firstName"]:
        raise Problem("Enter the worker's first name.")
    if out["gender"] not in ("", "M", "F", "O"):
        raise Problem("Choose the gender from the list.")
    for k, label in (("dob", "date of birth"), ("doj", "date of joining")):
        if out[k] and not ISO.match(out[k]):
            raise Problem(f"The {label} is not a date.")
    if not out["doj"]:
        raise Problem("Enter the date of joining.")
    if out["dob"]:
        age = (date.fromisoformat(out["doj"]) - date.fromisoformat(out["dob"])).days / 365.25
        if age < 18:
            raise Problem("The worker must be at least 18 years old on the date of joining.")
    if out["email"] and not EMAIL.match(out["email"]):
        raise Problem("That is not an e-mail address.")
    if out["phone"] and not phone10(out["phone"]):
        raise Problem("Enter a 10-digit mobile number.")
    if not out["email"] and not out["phone"]:
        raise Problem("Enter a mobile number or an e-mail address: the worker signs in with it.")
    co_id = con.get("companyId")
    for k, coll in (("deptId", "depts"), ("desigId", "desigs"), ("locationId", "locations"), ("shiftId", "shifts")):
        if out[k]:
            rec = repo.get_records(conn, coll, [out[k]]).get(out[k])
            if not rec or rec.get("companyId") != co_id:
                raise Problem("Choose the department, designation, location and shift from the lists.")
    emps = repo.employees_index(conn)
    ph = phone10(out["phone"])
    for e in emps.values():
        if e.get("id") == emp_id:
            continue
        if out["email"] and (e.get("email") or "").lower() == out["email"]:
            if e.get("status") == "exited":
                raise Problem(f"This person worked here before ({e.get('empNo')}). Ask the company's HR to rehire them.")
            if workforce.register_of(e) == "contract" and e.get("contractorId") != con.get("id"):
                raise Problem("This worker is already engaged through another contractor. A worker stays with one contractor: "
                              "ask the company's HR to end that engagement first.")
            raise Problem("Someone in PeopleDesk already has this e-mail address.")
        if ph and e.get("status") != "exited" and phone10(e.get("phone")) == ph:
            if workforce.register_of(e) == "contract" and e.get("contractorId") != con.get("id"):
                raise Problem("This worker is already engaged through another contractor. A worker stays with one contractor: "
                              "ask the company's HR to end that engagement first.")
            raise Problem("Someone in PeopleDesk already has this mobile number.")
    if any(find_user_by_login(conn, x)[1] for x in (out["email"], out["phone"]) if x):
        raise Problem("That e-mail address or mobile number belongs to a contractor's portal user.")
    return out


def _next_emp_no(conn, co: dict) -> str:
    seq = conn.execute(text("SELECT data FROM app_kv WHERE k='seq' FOR UPDATE")).scalar()
    seq = repo.loads(seq) or {}
    used = {e.get("empNo") for e in repo.records_where(conn, "employees", "company_id", co["id"])}
    n = int(seq.get(f"emp-{co['id']}") or 0) + 1
    code = co.get("code") or "EMP"
    while f"{code}-{n:05d}" in used:
        n += 1
    seq[f"emp-{co['id']}"] = n
    repo.set_singleton(conn, "seq", seq)
    return f"{code}-{n:05d}"


def add_worker(conn, con: dict, user: dict, d: dict) -> dict:
    if con.get("active") is False:
        raise Problem("This contractor is not active with the company.")
    out = _check_worker(conn, con, d, None)
    if con.get("licenceTo") and con["licenceTo"] < out["doj"]:
        raise Problem(f"Your labour licence runs only to {workforce.dmy(con['licenceTo'])}. Renew it with the company before adding workers.")
    active = [e for e in workers_of(conn, con) if e.get("status") != "exited"]
    if str(con.get("maxWorkers") or "").strip() and int(float(con["maxWorkers"])) <= len(active):
        raise Problem(f"Your licence allows {int(float(con['maxWorkers']))} workers and {len(active)} are engaged. Ask the company to update the licence first.")
    co = repo.get_records(conn, "companies", [con.get("companyId")]).get(con.get("companyId"))
    if not co:
        raise Problem("The company was not found.")
    if not out["shiftId"]:
        shifts = repo.records_where(conn, "shifts", "company_id", co["id"])
        out["shiftId"] = shifts[0]["id"] if shifts else ""
    now = int(time.time() * 1000)
    emp_id = uuid.uuid4().hex[:14]
    by = {"contractorId": con["id"], "userId": user["id"], "name": user.get("name", ""), "at": now}
    e = {"id": emp_id, "companyId": co["id"], "status": "active", "role": "employee", **out, "empNo": _next_emp_no(conn, co),
         "workerCategory": "contract", "contractorId": con["id"], "attGroup": "shift", "otEligible": True, "empType": "contract",
         "pfOn": True, "epsOn": True, "esiOn": True, "ptOn": True, "lwfOn": True, "taxRegime": "new", "payMode": "bank", "managerId": "",
         "salaryHist": [], "source": "contractor", "addedBy": by,
         "history": [{"date": out["doj"], "type": "Hire", "note": f"Contract worker added by {con.get('name')} ({user.get('name', '')})", "by": ""}],
         "reportingHist": [{"from": out["doj"], "managerId": "", "matrixManagerIds": [], "reason": "Joined", "by": "", "at": now}],
         "gradeHist": [{"from": out["doj"], "gradeId": "", "desigId": out["desigId"], "reason": "Joined", "by": "", "at": now}]}
    repo.upsert(conn, "employees", [e], None)
    repo.audit_add(conn, "Contract worker added by contractor", f"{e['firstName']} {e['lastName']} ({e['empNo']}), {con.get('name')}: {user.get('name', '')}",
                   emp_id, module="org", ref_type="employee", ref_id=emp_id)
    repo.bump_rev(conn)
    return e


def update_worker(conn, con: dict, user: dict, emp_id: str, d: dict) -> dict:
    e = repo.get_records(conn, "employees", [emp_id]).get(emp_id)
    if not e or e.get("contractorId") != con.get("id") or e.get("companyId") != con.get("companyId"):
        raise Problem("That worker is not one of yours.")
    if e.get("status") != "active":
        raise Problem("Only active workers can be corrected.")
    if emp_id in employees_with_access(conn, [emp_id]):
        raise Problem(f"{e.get('firstName')} has signed in and keeps their own details now. Ask them, or the company's HR, to change them.")
    out = _check_worker(conn, con, d, emp_id)
    changed = [k for k in WORKER_FIELDS if str(e.get(k) or "") != out[k]]
    if not changed:
        return e
    e.update(out)
    (e.setdefault("history", [])).append({"date": date.today().isoformat(), "type": "Details corrected by the contractor",
                                          "note": f"{', '.join(changed)} ({user.get('name', '')})", "by": ""})
    repo.upsert(conn, "employees", [e], None)
    repo.audit_add(conn, "Contract worker corrected by contractor", f"{e['firstName']} {e.get('lastName', '')}: {', '.join(changed)} ({user.get('name', '')})",
                   emp_id, module="org", ref_type="employee", ref_id=emp_id)
    repo.bump_rev(conn)
    return e


def mark_link_sent(conn, emp: dict):
    emp["accessLinkAt"] = int(time.time() * 1000)
    repo.upsert(conn, "employees", [emp], None)
    repo.bump_rev(conn)
