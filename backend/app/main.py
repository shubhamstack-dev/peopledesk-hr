"""
PeopleDesk HR API (the middle tier between the React app and MySQL).

  GET  /api/bootstrap        what the sign-in page needs (no session)
  POST /api/setup            first-time setup: group, first company, group administrator
  POST /api/setup/demo       disabled (no demo data in this build)
  POST /api/auth/login       e-mail and back-up password
  POST /api/auth/google      Google Identity Services ID token (verified here)
  POST /api/auth/microsoft   Microsoft Entra ID token from MSAL (verified here)
  POST /api/auth/demo        disabled
  POST /api/auth/logout
  POST /api/auth/password    change your own back-up password
  GET  /api/state            everything the signed-in person may see
  GET  /api/rev              cheap check for changes made by others
  POST /api/sync             save changes (records, roster, settings, activity log)
  GET  /api/admin/backup     whole database as one JSON file (group administrator)
  POST /api/admin/restore    replace everything from such a file (group administrator)
  POST /api/admin/wipe       erase everything (group administrator)
  GET  /api/doc-templates/fields     the database fields a Word template can use (HR)
  POST /api/doc-templates/scan       upload a .docx template and list its placeholders (HR)
  POST /api/doc-templates/preview    fill a template for one employee and download it, nothing saved (HR)
  POST /api/doc-templates/generate   fill it, give it a letter number and keep the file (HR)
  GET  /api/session          who is signed in: an employee or a contractor's portal user
  POST /api/auth/invite/check    what an access link is for (no session)
  POST /api/auth/invite/accept   set a password with an access link and sign in (no session)
  POST /api/access-link      HR: an access link for an employee or a contractor's portal user
  GET  /api/contractor/state         contractor portal: the contractor, its workers, the company's lists
  POST /api/contractor/workers       contractor portal: add a worker
  POST /api/contractor/workers/{id}  contractor portal: correct a worker before they sign in
  POST /api/contractor/workers/{id}/access   contractor portal: an access link for a worker
  POST /api/contractor/password      contractor portal: change your password
  POST /api/candidate-form/link      HR: a link with which a candidate fills in their details and CV
  POST /api/reimb/run                Finance or HR: pay the approved expense claims now (reimbursement run)
  POST /api/reimb/paid               Finance or HR: record the bank transfer of a reimbursement run
  POST /api/apply/open               the candidate's form, from that link (no session)
  POST /api/apply/save               the candidate saves or sends the form (no session)
"""
import logging
import base64
import os
import re
import time
import uuid
from typing import Any

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response as RawResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import text

from . import candform, cmail, cportal, doctemplates, email_templates, mailer, migrate, perf, policy, portal, reimb, reports, repo, training, workforce
from .collections import BY_NAME, SINGLETONS
from .config import APP_URL, CORS_ORIGINS, FRONTEND_DIST, MAX_UPLOAD_MB, UPLOAD_DIR
from .security import (active_employee, current_user, end_session, get_pw_hash, hash_password, require_csrf,
                       session_subject, set_google_sub, set_pw_hash, start_session, verify_password)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("peopledesk")

app = FastAPI(title="PeopleDesk HR API", version="2.0")


@app.on_event("startup")
def _migrate():
    migrate.run(repo.engine)
    # 2.15: automatic reimbursement runs on each company's cycle
    # mail set up later in the app is used too: the reminder sends only while mail is configured
    reimb.start(repo.engine, send=lambda *a, **k: mailer.send(*a, **k) if mailer.configured() else None)
    # Admin: e-mail a saved report on its schedule
    reports.start(repo.engine, send=lambda *a, **k: mailer.send(*a, **k) if mailer.configured() else None)
    # 2.19: replies from candidates (and HR) to the conversation, read from the replies mailbox when it is set up
    cmail.start(repo.engine, store=lambda data, name, mime, co, owner: _store_file(data, name, mime, co, owner))
if CORS_ORIGINS:
    app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_credentials=True,
                       allow_methods=["GET", "POST"], allow_headers=["content-type", "x-peopledesk"])

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@app.exception_handler(policy.Rejected)
async def rejected_handler(_req, exc):
    return JSONResponse({"detail": f"Not saved: {exc}"}, status_code=403)


# ---------------------------------------------------------------- bodies
class LoginBody(BaseModel):
    email: str
    password: str


class GoogleBody(BaseModel):
    credential: str


class MicrosoftBody(BaseModel):
    credential: str


class DemoBody(BaseModel):
    empId: str


class PasswordBody(BaseModel):
    current: str = ""
    new: str = Field(min_length=10, max_length=200)


class SetupBody(BaseModel):
    state: dict
    adminId: str
    password: str = Field(min_length=10, max_length=200)


class StateBody(BaseModel):
    state: dict


class SyncBody(BaseModel):
    upsert: dict[str, list[dict]] = {}
    delete: dict[str, list[str]] = {}
    singletons: dict[str, Any] = {}
    rosterSet: list[dict] = []
    rosterDel: list[dict] = []
    audit: list[dict] = []


# ---------------------------------------------------------------- helpers
def _ctx(conn, me) -> policy.Ctx:
    return policy.make_ctx(me, repo.employees_index(conn), repo.registered_companies(conn))


def _public_settings(conn) -> dict:
    s = repo.get_singleton(conn, "settings") or {}
    return {"googleClientId": s.get("googleClientId", ""), "msClientId": s.get("msClientId", ""), "msTenantId": s.get("msTenantId", ""),
            "allowPassword": s.get("allowPassword", True),
            "allowDemo": False, "idleMin": s.get("idleMin", 30), "externalPassword": True}


def _find_by_email(conn, email: str):
    emp_id = conn.execute(text("SELECT id FROM employees WHERE email=:e ORDER BY (status='exited'), created_at LIMIT 1"),
                          {"e": email.strip().lower()}).scalar()
    return repo.get_records(conn, "employees", [emp_id]).get(emp_id) if emp_id else None


def _signed_in(resp: Response, conn, emp: dict, how: str):
    start_session(resp, emp["id"])
    repo.audit_add(conn, "Signed in", f"{emp.get('firstName', '')} {emp.get('lastName', '')}".strip() + f" ({how})", emp["id"])
    return {"ok": True, "me": emp["id"]}


def _validate_state(st: dict):
    if not isinstance(st.get("employees"), list) or not isinstance(st.get("companies"), list):
        raise HTTPException(400, "That is not data from this app.")


# ---------------------------------------------------------------- sign-in and setup
@app.get("/api/bootstrap")
def bootstrap():
    with repo.engine.connect() as conn:
        if repo.is_empty(conn):
            return {"needsSetup": True}
        s = _public_settings(conn)
        group = repo.get_singleton(conn, "group") or {}
        n_co = conn.execute(text("SELECT COUNT(*) FROM companies")).scalar()
        demo = []
        if s["allowDemo"]:
            emps = repo.employees_index(conn)
            mgrs = {e.get("managerId") for e in emps.values() if e.get("status") != "exited"}
            demo = sorted(
                ({"id": e["id"], "name": f"{e.get('firstName', '')} {e.get('lastName', '')}".strip(), "role": e.get("role"), "manager": e["id"] in mgrs}
                 for e in emps.values() if active_employee(e)),
                key=lambda x: (x["role"] != "super", x["name"]))
        return {"needsSetup": False, "group": group.get("name", ""), "companies": n_co, "settings": s, "demo": demo, "canRegister": True}


@app.post("/api/setup", dependencies=[Depends(require_csrf)])
def setup(body: SetupBody, resp: Response):
    _validate_state(body.state)
    admin = next((e for e in body.state["employees"] if e.get("id") == body.adminId), None)
    if not admin or admin.get("role") != "super" or not EMAIL.match(admin.get("email", "")):
        raise HTTPException(400, "The group administrator is missing from the setup data.")
    with repo.engine.begin() as conn:
        if not repo.is_empty(conn):
            raise HTTPException(409, "This system is already set up. Sign in instead.")
        repo.import_state(conn, body.state, body.adminId)
        set_pw_hash(conn, body.adminId, hash_password(body.password))
        repo.audit_add(conn, "System set up", admin.get("email"), body.adminId)
        repo.bump_rev(conn)
        return _signed_in(resp, conn, admin, "setup")


class RegisterBody(BaseModel):
    records: dict
    adminId: str
    password: str = Field(min_length=10, max_length=200)


_REG_TIMES: dict = {}
SHORT_CODE = re.compile(r"^[A-Z0-9]{2,6}$")


@app.post("/api/register", dependencies=[Depends(require_csrf)])
def register(body: RegisterBody, request: Request, resp: Response):
    """Another company registers on the platform: its company record, its starting masters (shift, leave types,
    pay components) and its administrator, who manages only that company. Everything must belong to the new company."""
    ip = (request.headers.get("x-forwarded-for") or (request.client.host if request.client else "")).split(",")[0].strip()
    now = time.time()
    recent = [x for x in _REG_TIMES.get(ip, []) if now - x < 3600]
    if len(recent) >= 5:
        raise HTTPException(429, "Too many registrations from this network. Try again in an hour.")
    recs = body.records or {}
    cos = recs.get("companies") or []
    if len(cos) != 1 or not isinstance(cos[0], dict):
        raise HTTPException(400, "Registration needs exactly one company.")
    co = cos[0]
    cid = str(co.get("id") or "")
    code = str(co.get("code") or "").strip().upper()
    if not cid or not SHORT_CODE.match(code) or not str(co.get("name") or "").strip():
        raise HTTPException(400, "Enter the company name and a short code of 2 to 6 letters or digits.")
    emps = recs.get("employees") or []
    if len(emps) != 1 or emps[0].get("id") != body.adminId:
        raise HTTPException(400, "Registration needs exactly one administrator.")
    admin = emps[0]
    email = str(admin.get("email") or "").strip().lower()
    if not EMAIL.match(email):
        raise HTTPException(400, "Enter a valid e-mail address.")
    for coll, items in recs.items():
        if coll not in BY_NAME or not isinstance(items, list):
            raise HTTPException(400, f"Unknown data: {coll}")
        for r in items:
            if not isinstance(r, dict) or not r.get("id"):
                raise HTTPException(400, "Malformed registration data.")
            owner = r.get("id") if coll == "companies" else r.get("companyId")
            if owner != cid or (r.get("empId") and r.get("empId") != body.adminId):
                raise HTTPException(400, "Registration data may only describe the new company.")
    with repo.engine.begin() as conn:
        if repo.is_empty(conn):
            raise HTTPException(409, "The platform is not set up yet.")
        if conn.execute(text("SELECT COUNT(*) FROM companies WHERE UPPER(code)=:c"), {"c": code}).scalar():
            raise HTTPException(409, "That short code is already used by another company. Choose another.")
        if _find_by_email(conn, email):
            raise HTTPException(409, "An account with this e-mail already exists. Sign in instead.")
        if candform.signin_companies(conn, email):
            raise HTTPException(409, "This e-mail address is used for a candidate's sign-in. Register with your work e-mail address.")
        for coll, items in recs.items():
            if repo.get_records(conn, coll, [r["id"] for r in items]):
                raise HTTPException(409, "Registration data clashes with existing records. Try again.")
        co.update({"code": code, "registeredAt": int(now * 1000), "registeredBy": body.adminId, "source": "register"})
        admin.update({"email": email, "role": "hr", "hrCompanies": [], "status": "active", "blocked": False, "managerId": "", "companyId": cid})
        for coll, items in recs.items():
            repo.upsert(conn, coll, items, body.adminId)
        seq = repo.get_singleton(conn, "seq") or {}
        seq[f"emp-{cid}"] = max(int(seq.get(f"emp-{cid}") or 0), 1)
        repo.set_singleton(conn, "seq", seq)
        set_pw_hash(conn, body.adminId, hash_password(body.password))
        repo.audit_add(conn, "Company registered", f"{co.get('name')} ({code}): {email}", body.adminId)
        repo.bump_rev(conn)
        out = _signed_in(resp, conn, admin, "registration")
    _REG_TIMES[ip] = recent + [now]
    return out


@app.post("/api/setup/demo", dependencies=[Depends(require_csrf)])
def setup_demo(body: StateBody):
    raise HTTPException(404, "Demo data is not available.")
    _validate_state(body.state)
    with repo.engine.begin() as conn:
        if not repo.is_empty(conn):
            raise HTTPException(409, "This system is already set up.")
        repo.import_state(conn, body.state)
        repo.bump_rev(conn)
    return {"ok": True}


@app.post("/api/auth/login", dependencies=[Depends(require_csrf)])
def login(body: LoginBody, resp: Response):
    """E-mail (or mobile number) and password. Contract workers and contractors' portal users usually have no
    company Google or Microsoft account, so they may use a password even where passwords are off for staff."""
    time.sleep(0.3)   # slows down password guessing
    bad = HTTPException(401, "E-mail or password is incorrect. Employees added from Google or Microsoft sign in with Google or Microsoft.")
    with repo.engine.begin() as conn:
        allow = _public_settings(conn)["allowPassword"]
        emp = _find_by_email(conn, body.email) if "@" in body.email else portal.find_employee_by_phone(conn, body.email)
        if not emp:
            con, user = portal.find_user_by_login(conn, body.email)
            if not user:
                # 2.17: a candidate's sign-in
                cand = _candidate_login(conn, body.email, body.password)
                if not cand:
                    raise bad
                return _candidate_signed_in(resp, conn, cand)
            if not verify_password(portal.get_pw(conn, user["id"]), body.password)[0]:
                raise bad
            if not portal.is_open(con, user):
                raise HTTPException(403, "This account is not active. Ask the company's HR.")
            start_session(resp, portal.PORTAL_PREFIX + user["id"])
            portal.note_login(conn, user["id"])
            repo.audit_add(conn, "Contractor signed in", f"{user.get('name')} ({con.get('name')})", None)
            return {"ok": True, "kind": "contractor"}
        staff_off = not allow and workforce.register_of(emp) != "contract"
        ok, rehash = verify_password(get_pw_hash(conn, emp["id"]), body.password)
        if not ok or staff_off:
            # 2.17: a candidate whose mobile number is also an employee's signs in with their own password
            cand = _candidate_login(conn, body.email, body.password) if "@" not in body.email else None
            if cand:
                return _candidate_signed_in(resp, conn, cand)
        if staff_off:
            raise HTTPException(403, "Password sign-in is switched off. Sign in with Google.")
        if not ok:
            raise bad
        if not active_employee(emp):
            raise HTTPException(403, "This account is not active.")
        if rehash:
            set_pw_hash(conn, emp["id"], hash_password(body.password))
        return _signed_in(resp, conn, emp, "password")


@app.post("/api/auth/google", dependencies=[Depends(require_csrf)])
def login_google(body: GoogleBody, resp: Response):
    from google.auth.transport import requests as grequests
    from google.oauth2 import id_token

    with repo.engine.begin() as conn:
        client_id = _public_settings(conn)["googleClientId"]
        if not client_id:
            raise HTTPException(400, "Google sign-in is not set up.")
        try:
            p = id_token.verify_oauth2_token(body.credential, grequests.Request(), client_id)
        except ValueError:
            raise HTTPException(401, "The Google sign-in was not for this application. Try again.")
        if not p.get("email_verified"):
            raise HTTPException(401, "Google did not confirm this e-mail address.")
        emp = _find_by_email(conn, p["email"])
        if not emp:
            raise HTTPException(403, f"{p['email']} is not set up as an employee. Ask HR to sync users from Google Workspace.")
        co = repo.get_records(conn, "companies", [emp.get("companyId")]).get(emp.get("companyId")) or {}
        if co.get("domain") and p.get("hd") and p["hd"].lower() != co["domain"].lower():
            raise HTTPException(403, f"Sign in with your {co['domain']} account.")
        if not active_employee(emp):
            raise HTTPException(403, "This account is not active.")
        set_google_sub(conn, emp["id"], p["sub"])
        return _signed_in(resp, conn, emp, "Google")


GUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_MS_KEYS: dict = {}


@app.post("/api/auth/microsoft", dependencies=[Depends(require_csrf)])
def login_microsoft(body: MicrosoftBody, resp: Response):
    """Microsoft Entra ID (Azure AD): the browser gets an ID token with MSAL, it is verified here."""
    import jwt
    with repo.engine.begin() as conn:
        s = _public_settings(conn)
        cid, tid = s["msClientId"].strip(), s["msTenantId"].strip().lower()
        if not cid or not GUID.match(tid):
            raise HTTPException(400, "Microsoft sign-in is not set up.")
        try:
            if tid not in _MS_KEYS:
                _MS_KEYS[tid] = jwt.PyJWKClient(f"https://login.microsoftonline.com/{tid}/discovery/v2.0/keys", cache_keys=True)
            key = _MS_KEYS[tid].get_signing_key_from_jwt(body.credential).key
            p = jwt.decode(body.credential, key, algorithms=["RS256"], audience=cid,
                           issuer=f"https://login.microsoftonline.com/{tid}/v2.0", leeway=120)
        except Exception as x:  # bad signature, wrong app or tenant, expired
            log.warning("Microsoft sign-in rejected: %s", x)
            raise HTTPException(401, "The Microsoft sign-in was not for this application. Try again.")
        emails = [v.strip().lower() for v in (p.get("email"), p.get("preferred_username"), p.get("upn")) if v and "@" in v]
        emp = next((e for e in (_find_by_email(conn, m) for m in dict.fromkeys(emails)) if e), None)
        if not emp:
            raise HTTPException(403, f"{emails[0] if emails else 'This account'} is not set up as an employee. Ask HR to sync users from Microsoft.")
        if not active_employee(emp):
            raise HTTPException(403, "This account is not active.")
        return _signed_in(resp, conn, emp, "Microsoft")


@app.post("/api/auth/demo", dependencies=[Depends(require_csrf)])
def login_demo(body: DemoBody, resp: Response):
    raise HTTPException(403, "Demo sign-in is not available.")
    with repo.engine.begin() as conn:
        if not _public_settings(conn)["allowDemo"]:
            raise HTTPException(403, "Demo sign-in is switched off.")
        emp = repo.get_records(conn, "employees", [body.empId]).get(body.empId)
        if not active_employee(emp):
            raise HTTPException(403, "This account is not active.")
        return _signed_in(resp, conn, emp, "demo")


@app.post("/api/auth/logout", dependencies=[Depends(require_csrf)])
def logout(resp: Response):
    end_session(resp)
    return {"ok": True}


def _candidate_signed_in(resp: Response, conn, cand: dict):
    why = candform.session_problem(cand, candform.get_cred(conn, cand["id"]))
    if why:
        raise HTTPException(403, why)
    start_session(resp, candform.SESSION_PREFIX + cand["id"])
    candform.note_login(conn, cand["id"])
    repo.audit_add(conn, "Candidate signed in", cand.get("name") or "", None, module="recruitment", ref_type="candidate", ref_id=cand["id"])
    return {"ok": True, "kind": "candidate"}


def _candidate_login(conn, login: str, password: str):
    """The candidate whose sign-in this is and whose password matches, or None."""
    for cand in candform.candidates_for_login(conn, login):
        if verify_password(candform.get_cred(conn, cand["id"])["pw"], password)[0]:
            return cand
    return None


# ---------------------------------------------------------------- access links and the contractor portal
class InviteBody(BaseModel):
    token: str
    password: str = ""


class AccessLinkBody(BaseModel):
    empId: str = ""
    contractorId: str = ""
    userId: str = ""
    send: bool = True


class WorkerBody(BaseModel):
    firstName: str = ""
    lastName: str = ""
    gender: str = ""
    dob: str = ""
    phone: str = ""
    email: str = ""
    doj: str = ""
    deptId: str = ""
    desigId: str = ""
    locationId: str = ""
    shiftId: str = ""


class PortalPasswordBody(BaseModel):
    current: str
    new: str = Field(min_length=10, max_length=200)


def _base_url(request: Request) -> str:
    return APP_URL or str(request.base_url).rstrip("/")


def _portal_problem(fn, *args):
    try:
        return fn(*args)
    except portal.Problem as e:
        raise HTTPException(400, str(e)) from None


@app.get("/api/session")
def session_kind(request: Request):
    """Whether the signed-in person is an employee (the main app) or a contractor's portal user (the portal)."""
    sub = session_subject(request)
    with repo.engine.connect() as conn:
        if sub.startswith(portal.PORTAL_PREFIX):
            con, user = portal.get_user(conn, sub[len(portal.PORTAL_PREFIX):])
            if not portal.is_open(con, user):
                raise HTTPException(401, "This account is not active.")
            return {"kind": "contractor"}
        if sub.startswith(candform.SESSION_PREFIX):
            cid = sub[len(candform.SESSION_PREFIX):]
            cand = repo.get_records(conn, "cands", [cid]).get(cid)
            why = candform.session_problem(cand, candform.get_cred(conn, cid))
            if why:
                raise HTTPException(401, why)
            return {"kind": "candidate"}
        emp = repo.get_records(conn, "employees", [sub]).get(sub)
        if not active_employee(emp):
            raise HTTPException(401, "This account is not active.")
        return {"kind": "employee"}


def _invite_target(conn, claims: dict):
    """(name, company name, sign-in name, current password hash, save the password, sign in)"""
    if claims["k"] == "emp":
        emp = repo.get_records(conn, "employees", [claims["sub"]]).get(claims["sub"])
        if not active_employee(emp):
            raise portal.Problem("This account is not active. Ask the company's HR.")
        co = repo.get_records(conn, "companies", [emp.get("companyId")]).get(emp.get("companyId")) or {}
        return (f"{emp.get('firstName', '')} {emp.get('lastName', '')}".strip(), co.get("legalName") or co.get("name", ""),
                emp.get("email") or emp.get("phone") or "", get_pw_hash(conn, emp["id"]), emp)
    con, user = portal.get_user(conn, claims["sub"])
    if not portal.is_open(con, user):
        raise portal.Problem("This account is not active. Ask the company's HR.")
    co = repo.get_records(conn, "companies", [con.get("companyId")]).get(con.get("companyId")) or {}
    return (user.get("name", ""), co.get("legalName") or co.get("name", ""), user.get("email") or user.get("phone") or "",
            portal.get_pw(conn, user["id"]), (con, user))


@app.post("/api/auth/invite/check", dependencies=[Depends(require_csrf)])
def invite_check(body: InviteBody):
    with repo.engine.connect() as conn:
        claims = _portal_problem(portal.read_invite, body.token)
        name, company, login_as, pw, _ = _portal_problem(_invite_target, conn, claims)
        _portal_problem(portal.invite_still_valid, claims, pw)
        return {"name": name, "company": company, "login": login_as, "kind": "contractor" if claims["k"] == "con" else "employee"}


@app.post("/api/auth/invite/accept", dependencies=[Depends(require_csrf)])
def invite_accept(body: InviteBody, resp: Response):
    if len(body.password) < 10 or len(body.password) > 200:
        raise HTTPException(400, "Use a password of at least 10 characters.")
    time.sleep(0.2)
    with repo.engine.begin() as conn:
        claims = _portal_problem(portal.read_invite, body.token)
        name, _company, _login, pw, who = _portal_problem(_invite_target, conn, claims)
        _portal_problem(portal.invite_still_valid, claims, pw)
        if claims["k"] == "emp":
            set_pw_hash(conn, who["id"], hash_password(body.password))
            repo.audit_add(conn, "Password set with an access link", name, who["id"])
            return _signed_in(resp, conn, who, "access link")
        con, user = who
        portal.set_pw(conn, user["id"], con["id"], hash_password(body.password))
        portal.note_login(conn, user["id"])
        start_session(resp, portal.PORTAL_PREFIX + user["id"])
        repo.audit_add(conn, "Contractor set a password with an access link", f"{name} ({con.get('name')})", None)
        return {"ok": True, "kind": "contractor"}


def _send_link(co_id, to: str, name: str, who: str, company: str, url: str, want: bool) -> bool:
    if not (want and to and "@" in to and mailer.configured()):
        return False
    with repo.engine.connect() as conn:
        subject, text_ = email_templates.render(conn, co_id, "access.invite",
                                                 {"name": name, "who": who, "company": company, "url": url, "inviteDays": portal.INVITE_DAYS})
    try:
        mailer.send([to], subject, text_)
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("Access link mail failed: %s", e)
        return False


@app.post("/api/access-link")
def access_link(body: AccessLinkBody, request: Request, me=Depends(current_user)):
    """HR: a link with which an employee (a contract worker, or anyone without Google or Microsoft) or a contractor's
    portal user sets a password. It works once, for 7 days. Sent by e-mail when the server can; always returned so
    HR can pass it on another way (a text message, for instance)."""
    with repo.engine.begin() as conn:
        ctx = _ctx(conn, me)
        if body.empId:
            emp = repo.get_records(conn, "employees", [body.empId]).get(body.empId)
            if not emp or not ctx.is_hr_for(emp.get("companyId")):
                raise HTTPException(403, "Only HR for this employee's company can give access.")
            if not active_employee(emp):
                raise HTTPException(400, "This employee is not active.")
            token = portal.make_invite("emp", emp["id"], get_pw_hash(conn, emp["id"]))
            name = f"{emp.get('firstName', '')} {emp.get('lastName', '')}".strip()
            to, co_id = emp.get("email") or "", emp.get("companyId")
            portal.mark_link_sent(conn, emp)
        else:
            con = repo.get_records(conn, "contractors", [body.contractorId]).get(body.contractorId)
            if not con or not ctx.is_hr_for(con.get("companyId")):
                raise HTTPException(403, "Only HR for this contractor's company can give access.")
            user = next((u for u in portal.portal_users(con) if u["id"] == body.userId), None)
            if not portal.is_open(con, user):
                raise HTTPException(400, "Save the portal user first, and make sure they and the contractor are active.")
            token = portal.make_invite("con", user["id"], portal.get_pw(conn, user["id"]))
            name, to, co_id = user.get("name", ""), user.get("email") or "", con.get("companyId")
        co = repo.get_records(conn, "companies", [co_id]).get(co_id) or {}
        url = portal.invite_url(_base_url(request), token)
        repo.audit_add(conn, "Access link created", name, me["id"])
    sent = _send_link(co_id, to, name, f"{me.get('firstName', '')} {me.get('lastName', '')}".strip() or "HR", co.get("legalName") or co.get("name", ""), url, body.send)
    return {"url": url, "sent": sent, "to": to if sent else "", "days": portal.INVITE_DAYS}


# ---------------------------------------------------------------- 2.11: the candidate's application form
class CandLinkBody(BaseModel):
    candId: str
    send: bool = True


class CandFormBody(BaseModel):
    token: str
    data: dict = Field(default_factory=dict)
    cv: dict | None = None
    submit: bool = False


def _cand_problem(fn, *args):
    try:
        return fn(*args)
    except candform.Problem as e:
        raise HTTPException(400, str(e)) from None


@app.post("/api/candidate-form/link")
def candidate_form_link(body: CandLinkBody, request: Request, me=Depends(current_user)):
    """HR: a link with which a candidate fills in their details and attaches their CV. It works for 14 days and
    stops working when a newer link is sent or the candidate joins. Sent by e-mail when the server can."""
    with repo.engine.begin() as conn:
        ctx = _ctx(conn, me)
        cand = repo.get_records(conn, "cands", [body.candId]).get(body.candId)
        if not cand or not ctx.is_hr_for(cand.get("companyId")):
            raise HTTPException(403, "Only HR for this candidate's company can send the form.")
        # 2.17: the form is for candidates; an employee's details are kept on their employee record
        if candform.is_employee_login(conn, cand):
            raise HTTPException(400, f"{cand.get('email')} is an employee's e-mail address. The candidate form is filled in by "
                                     "candidates, not employees: give the candidate's own e-mail address.")
        if not candform.login_name(cand):
            raise HTTPException(400, "Add the candidate's e-mail address (or mobile number) first: they sign in with it to fill in the form.")
        rec, nonce = _cand_problem(candform.start, cand, me["id"])
        repo.upsert(conn, "cands", [rec], me["id"])
        repo.audit_add(conn, "Application form sent to a candidate", cand.get("name") or "", me["id"], module="recruitment", ref_type="candidate", ref_id=cand["id"])
        repo.bump_rev(conn)
        co = repo.get_records(conn, "companies", [cand.get("companyId")]).get(cand.get("companyId")) or {}
        url = candform.link_url(_base_url(request), candform.make_link(cand["id"], nonce))
        form = rec["form"]
        jobs = candform.job_titles(conn, cand)
    sent = False
    to = cand.get("email") or ""
    if body.send and to and mailer.configured():
        jobs = [j for j in (jobs or []) if j]
        job_label = jobs[0] if len(jobs) == 1 else ""
        with repo.engine.connect() as conn:
            subject, text_ = email_templates.render(conn, cand.get("companyId"), "candidate.link", {
                "name": cand.get("name") or "", "company": co.get("legalName") or co.get("name", ""), "url": url, "linkDays": candform.LINK_DAYS,
                "jobLabel": job_label, "what": f" for the position of {', '.join(jobs[:3])}" if jobs else "",
                "skillsNote": " and your level in the skills the job needs" if jobs else ""})
        try:
            mailer.send([to], subject, text_)
            sent = True
        except Exception as e:  # noqa: BLE001
            log.warning("Candidate form mail failed: %s", e)
    return {"url": url, "sent": sent, "to": to if sent else "", "days": candform.LINK_DAYS, "form": form}


class ApplyAccountBody(BaseModel):
    token: str
    password: str = ""


class CandSaveBody(BaseModel):
    data: dict = Field(default_factory=dict)
    cv: dict | None = None
    submit: bool = False


def _session_sub(request: Request) -> str:
    try:
        return session_subject(request)
    except HTTPException:
        return ""


@app.post("/api/apply/open", dependencies=[Depends(require_csrf)])
def apply_open(body: CandFormBody, request: Request):
    """2.17: the link page, before sign-in. Says whose link it is and whether to create a sign-in or sign in; shows
    nothing the candidate entered. Whoever is signed in on this browser is reported, so the page can stop an employee."""
    with repo.engine.connect() as conn:
        cand, nonce = _cand_problem(candform.read_link, conn, body.token)
        out = candform.link_view(conn, cand, nonce, candform.get_cred(conn, cand["id"]))
    sub = _session_sub(request)
    out["signedIn"] = ("this" if sub == candform.SESSION_PREFIX + cand["id"] else "candidate" if sub.startswith(candform.SESSION_PREFIX)
                       else "contractor" if sub.startswith(portal.PORTAL_PREFIX) else "employee" if sub else "")
    return out


@app.post("/api/apply/account", dependencies=[Depends(require_csrf)])
def apply_account(body: ApplyAccountBody, resp: Response):
    """2.17: the candidate creates their sign-in with HR's link (or, with a newer link, sets a new password),
    and is signed in."""
    if not (candform.PW_MIN <= len(body.password) <= candform.PW_MAX):
        raise HTTPException(400, f"Use a password of at least {candform.PW_MIN} characters.")
    time.sleep(0.2)
    with repo.engine.begin() as conn:
        cand, nonce = _cand_problem(candform.read_link, conn, body.token)
        cred = candform.get_cred(conn, cand["id"])
        if cred.get("setWith") == nonce:
            raise HTTPException(400, "A password was already set with this link. Sign in with it, or ask HR for a new link.")
        why = candform.account_problem(conn, cand)
        if why:
            raise HTTPException(400, why)
        candform.set_cred(conn, cand["id"], hash_password(body.password), nonce)
        candform.note_account(conn, cand, first=not cred.get("pw"))
        candform.note_login(conn, cand["id"])
        repo.audit_add(conn, "Candidate created their sign-in" if not cred.get("pw") else "Candidate set a new password",
                       cand.get("name") or "", None, module="recruitment", ref_type="candidate", ref_id=cand["id"])
    start_session(resp, candform.SESSION_PREFIX + cand["id"])
    return {"ok": True, "kind": "candidate", "login": candform.login_name(cand)}


def current_candidate(request: Request, _=Depends(require_csrf)) -> dict:
    """2.17: the signed-in candidate. Employees and contractors' portal users are refused: the form is the candidate's."""
    sub = session_subject(request)
    if not sub.startswith(candform.SESSION_PREFIX):
        raise HTTPException(403, "The candidate form is filled in by the candidate, signed in as a candidate.")
    cid = sub[len(candform.SESSION_PREFIX):]
    with repo.engine.connect() as conn:
        cand = repo.get_records(conn, "cands", [cid]).get(cid)
        why = candform.session_problem(cand, candform.get_cred(conn, cid))
    if why:
        raise HTTPException(401, why)
    return cand


@app.get("/api/candidate/form")
def candidate_form(cand=Depends(current_candidate)):
    with repo.engine.connect() as conn:
        return {**candform.public_view(conn, cand), "login": candform.login_name(cand)}


@app.post("/api/candidate/form")
def candidate_form_save(body: CandSaveBody, cand=Depends(current_candidate)):
    time.sleep(0.1)
    with repo.engine.begin() as conn:
        rec = _cand_problem(candform.save, conn, cand, body.data, body.cv, body.submit)
        return {**candform.public_view(conn, rec), "login": candform.login_name(rec)}


@app.post("/api/candidate/password")
def candidate_password(body: PortalPasswordBody, cand=Depends(current_candidate)):
    time.sleep(0.2)
    with repo.engine.begin() as conn:
        cred = candform.get_cred(conn, cand["id"])
        if not verify_password(cred["pw"], body.current)[0]:
            raise HTTPException(400, "The current password is not right.")
        candform.set_cred(conn, cand["id"], hash_password(body.new), cred.get("setWith") or "")
        repo.audit_add(conn, "Candidate changed their password", cand.get("name") or "", None, module="recruitment", ref_type="candidate", ref_id=cand["id"])
    return {"ok": True}


def current_portal_user(request: Request, _=Depends(require_csrf)):
    sub = session_subject(request)
    if not sub.startswith(portal.PORTAL_PREFIX):
        raise HTTPException(403, "This is for contractors' portal users.")
    with repo.engine.connect() as conn:
        con, user = portal.get_user(conn, sub[len(portal.PORTAL_PREFIX):])
    if not portal.is_open(con, user):
        raise HTTPException(401, "This account is not active.")
    return con, user


@app.get("/api/contractor/state")
def contractor_state(who=Depends(current_portal_user)):
    con, user = who
    with repo.engine.connect() as conn:
        return {"state": portal.state(conn, con, user, mailer.configured()), "rev": repo.rev(conn)}


@app.post("/api/contractor/workers")
def contractor_add(body: WorkerBody, who=Depends(current_portal_user)):
    con, user = who
    with repo.engine.begin() as conn:
        e = _portal_problem(portal.add_worker, conn, con, user, body.model_dump())
        return {"ok": True, "id": e["id"], "empNo": e["empNo"]}


@app.post("/api/contractor/workers/{emp_id}")
def contractor_update(emp_id: str, body: WorkerBody, who=Depends(current_portal_user)):
    con, user = who
    with repo.engine.begin() as conn:
        _portal_problem(portal.update_worker, conn, con, user, emp_id, body.model_dump())
        return {"ok": True}


class SendBody(BaseModel):
    send: bool = True


@app.post("/api/contractor/workers/{emp_id}/access")
def contractor_access(emp_id: str, body: SendBody, request: Request, who=Depends(current_portal_user)):
    con, user = who
    with repo.engine.begin() as conn:
        emp = repo.get_records(conn, "employees", [emp_id]).get(emp_id)
        if not emp or emp.get("contractorId") != con.get("id") or emp.get("companyId") != con.get("companyId"):
            raise HTTPException(403, "That worker is not one of yours.")
        if not active_employee(emp):
            raise HTTPException(400, "This worker is not active.")
        if portal.employees_with_access(conn, [emp_id]):
            # a link sets a new password: once the worker is in, only HR may do that
            raise HTTPException(400, f"{emp.get('firstName')} has already signed in. If they forgot their password, ask the company's HR for a new link.")
        token = portal.make_invite("emp", emp["id"], get_pw_hash(conn, emp["id"]))
        portal.mark_link_sent(conn, emp)
        co = repo.get_records(conn, "companies", [con.get("companyId")]).get(con.get("companyId")) or {}
        repo.audit_add(conn, "Access link created by contractor", f"{emp.get('firstName', '')} {emp.get('lastName', '')} ({user.get('name')}, {con.get('name')})",
                       emp["id"], module="org", ref_type="employee", ref_id=emp["id"])
    url = portal.invite_url(_base_url(request), token)
    name = f"{emp.get('firstName', '')} {emp.get('lastName', '')}".strip()
    sent = _send_link(emp.get("email") or "", name, con.get("name", "Your contractor"), co.get("legalName") or co.get("name", ""), url, body.send)
    return {"url": url, "sent": sent, "to": emp.get("email") if sent else "", "days": portal.INVITE_DAYS}


@app.post("/api/contractor/password")
def contractor_password(body: PortalPasswordBody, who=Depends(current_portal_user)):
    con, user = who
    with repo.engine.begin() as conn:
        if not verify_password(portal.get_pw(conn, user["id"]), body.current)[0]:
            raise HTTPException(400, "Your current password is not right.")
        portal.set_pw(conn, user["id"], con["id"], hash_password(body.new))
    return {"ok": True}


@app.post("/api/auth/password")
def change_password(body: PasswordBody, me=Depends(current_user)):
    with repo.engine.begin() as conn:
        stored = get_pw_hash(conn, me["id"])
        if stored and not verify_password(stored, body.current)[0]:
            raise HTTPException(400, "Your current password is not right.")
        set_pw_hash(conn, me["id"], hash_password(body.new))
        repo.audit_add(conn, "Password changed", "", me["id"])
    return {"ok": True}


# ---------------------------------------------------------------- data
@app.get("/api/state")
def get_state(me=Depends(current_user)):
    with repo.engine.connect() as conn:
        st = repo.load_state(conn)
        ctx = policy.make_ctx(me, {e["id"]: e for e in st["employees"]}, {c["id"] for c in st["companies"] if c.get("source") == "register"})
        rev = repo.rev(conn)
    return {"state": policy.redact_state(st, ctx), "me": me["id"], "rev": rev}


@app.get("/api/rev")
def get_rev(_me=Depends(current_user)):
    with repo.engine.connect() as conn:
        return {"rev": repo.rev(conn)}


@app.post("/api/sync")
def sync(body: SyncBody, me=Depends(current_user)):
    """All or nothing: if any change is refused, none is saved and the reason is returned."""
    with repo.engine.begin() as conn:
        ctx = _ctx(conn, me)
        guard = workforce.Guard(conn)       # attendance locked for payroll, notice for shift changes (everyone, HR too)
        for coll, recs in body.upsert.items():
            if coll not in BY_NAME:
                raise HTTPException(400, f"Unknown data: {coll}")
            olds = repo.get_records(conn, coll, [r.get("id") for r in recs])
            keep = []
            for r in recs:
                if not r.get("id"):
                    raise HTTPException(400, "A record without an id")
                if coll == "employees":
                    for k in ("pwHash", "pwSalt", "googleSub"):
                        r.pop(k, None)
                _guarded(guard.check_record, coll, r, olds.get(r["id"]), ctx.emps)
                _guarded(guard.check_attendance_request, coll, r, olds.get(r["id"]), ctx.emps, ctx.id)
                rec = policy.check_upsert(conn, coll, r, olds.get(r["id"]), ctx)
                if coll == "contractors":
                    try:
                        rec = portal.check_contractor(conn, rec, olds.get(r["id"]))
                    except portal.Problem as e:
                        raise policy.Rejected(str(e)) from None
                keep.append(rec)
            repo.upsert(conn, coll, keep, me["id"])
            if coll == "payRuns":
                guard.forget_runs()
        comp_cycles = set()   # salary-planning cycles touched: budgets are checked once everything is saved
        for coll, recs in body.upsert.items():
            if coll in ("compBudgets", "compRecs"):
                comp_cycles |= {r.get("cycleId") for r in recs}
            elif coll == "compCycles":
                comp_cycles |= {r.get("id") for r in recs}
        for coll, ids in body.delete.items():
            if coll not in BY_NAME:
                raise HTTPException(400, f"Unknown data: {coll}")
            olds = repo.get_records(conn, coll, ids)
            for i in ids:
                if i in olds:
                    _guarded(guard.check_record, coll, None, olds[i], ctx.emps)
                    policy.check_delete(conn, coll, olds[i], ctx)
                    if coll in ("compBudgets", "compRecs"):
                        comp_cycles.add(olds[i].get("cycleId"))
            repo.delete(conn, coll, list(olds))
        policy.check_comp_budgets(conn, comp_cycles, ctx)
        for k, v in body.singletons.items():
            if k not in SINGLETONS:
                raise HTTPException(400, f"Unknown setting: {k}")
            policy.check_singleton(k, ctx)
            if k == "seq" and not ctx.is_super:
                # counters only go up, and one company cannot reset another's
                old = repo.get_singleton(conn, "seq") or {}
                v = {**old, **{n: max(int(old.get(n) or 0), int(x or 0)) for n, x in (v or {}).items() if isinstance(x, (int, float)) or str(x).isdigit()}}
            repo.set_singleton(conn, k, v)
        for e in body.rosterSet + body.rosterDel:
            policy.check_roster(e.get("empId"), ctx)
            emp = ctx.emps.get(e.get("empId")) or {}
            _guarded(guard.check_roster, e.get("empId"), e.get("date"), e.get("value") if e in body.rosterSet else None, ctx.emps, ctx.is_hr_for(emp.get("companyId")))
        repo.roster_set(conn, [{"empId": e["empId"], "date": e["date"], "value": str(e["value"])} for e in body.rosterSet])
        repo.roster_del(conn, [{"empId": e["empId"], "date": e["date"]} for e in body.rosterDel])
        # time and shift controls, on the roster as saved (the whole batch is undone if a blocking control is broken)
        touched: dict = {}
        for e in body.rosterSet + body.rosterDel:
            touched.setdefault(e.get("empId"), set()).add(e.get("date"))
        for emp_id, days in touched.items():
            emp = ctx.emps.get(emp_id) or {}
            _guarded(guard.check_controls, emp_id, sorted(days), ctx.emps, ctx.is_hr_for(emp.get("companyId")))
        for a in body.audit[:200]:
            repo.audit_add(conn, a.get("what", ""), a.get("detail", ""), me["id"], a.get("at"), a.get("id"), a.get("module"), a.get("refType"), a.get("refId"))
        repo.bump_rev(conn)
        return {"ok": True, "rev": repo.rev(conn)}


def _guarded(fn, *args):
    try:
        fn(*args)
    except workforce.Problem as e:
        raise policy.Rejected(str(e)) from None


# ---------------------------------------------------------------- administration
def _require_super(me):
    if me.get("role") != "super":
        raise HTTPException(403, "Only the group administrator can do this.")


# ---------------------------------------------------------------- e-mail sending (group administrator)
class MailBody(BaseModel):
    host: str = ""
    port: int = 587
    security: str = "starttls"          # starttls | ssl | none
    auth: str = "password"              # password | m365 | none
    user: str = ""
    password: str = ""                  # empty keeps the saved one
    fromAddr: str = ""
    fromName: str = ""
    tenant: str = ""
    clientId: str = ""
    clientSecret: str = ""              # empty keeps the saved one


def _mail_view(d: dict, source: str) -> dict:
    keys = ("host", "port", "security", "auth", "user", "fromAddr", "fromName", "tenant", "clientId")
    return {**{k: d.get(k, "") for k in keys}, "hasPassword": bool(d.get("password")), "hasSecret": bool(d.get("clientSecret")), "source": source}


@app.get("/api/admin/mail")
def mail_get(me=Depends(current_user)):
    _require_super(me)
    with repo.engine.connect() as conn:
        d = mailer.stored(conn)
    if d.get("host"):
        return _mail_view(d, "app")
    env = mailer._env()
    return _mail_view(env, "env" if env.get("host") else "none")


@app.post("/api/admin/mail", dependencies=[Depends(require_csrf)])
def mail_save(body: MailBody, me=Depends(current_user)):
    _require_super(me)
    if body.security not in ("starttls", "ssl", "none") or body.auth not in ("password", "m365", "none"):
        raise HTTPException(400, "Choose the security and the sign-in method.")
    if body.host.strip():
        sender = (body.fromAddr or body.user).strip()
        if not EMAIL.match(sender):
            raise HTTPException(400, "Enter the address the mail comes from.")
        if body.auth == "m365" and not (GUID.match(body.tenant.strip()) and GUID.match(body.clientId.strip())):
            raise HTTPException(400, "For Microsoft 365, enter the Directory (tenant) ID and the Application (client) ID.")
    with repo.engine.begin() as conn:
        old = mailer.stored(conn)
        d = {"host": body.host.strip(), "port": int(body.port or 587), "security": body.security, "auth": body.auth,
             "user": body.user.strip(), "fromAddr": body.fromAddr.strip(), "fromName": body.fromName.strip()[:80],
             "tenant": body.tenant.strip().lower(), "clientId": body.clientId.strip(),
             "password": mailer.encrypt(body.password) if body.password else old.get("password", ""),
             "clientSecret": mailer.encrypt(body.clientSecret) if body.clientSecret else old.get("clientSecret", "")}
        if body.auth == "m365" and not d["clientSecret"]:
            raise HTTPException(400, "Enter the client secret of the Microsoft 365 app.")
        mailer.save(conn, d)
        repo.audit_add(conn, "E-mail settings changed", f"{d['host']} ({d['auth']})" if d["host"] else "switched off", me["id"])
    return _mail_view(d, "app" if d["host"] else "none")


class MailTestBody(BaseModel):
    to: str


@app.post("/api/admin/mail/test", dependencies=[Depends(require_csrf)])
def mail_test(body: MailTestBody, me=Depends(current_user)):
    _require_super(me)
    to = body.to.strip()
    if not EMAIL.match(to):
        raise HTTPException(400, "Enter the address to send the test to.")
    if not mailer.configured():
        raise HTTPException(400, "Save the server settings first.")
    try:
        mailer.send([to], "PeopleDesk HR: test e-mail", "This is a test from PeopleDesk HR. E-mail is working.")
    except Exception as e:  # noqa: BLE001 - shown to the administrator as it is
        raise HTTPException(502, f"Not sent: {str(e)[:300]}")
    return {"ok": True}


@app.get("/api/admin/backup")
def backup(me=Depends(current_user)):
    with repo.engine.connect() as conn:
        st = repo.load_state(conn)
        ctx = policy.make_ctx(me, {e["id"]: e for e in st["employees"]}, {c["id"] for c in st["companies"] if c.get("source") == "register"})
        if not ctx.is_hr:
            raise HTTPException(403, "Only an administrator can download a backup.")
        if ctx.is_super and not ctx.private:
            st["_auth"] = {i: {"pw": h, "google": g} for i, h, g in conn.execute(text("SELECT employee_id, pw_hash, google_sub FROM auth_credentials"))}
        else:
            # only this administrator's companies, without sign-in data
            policy._isolate(st, ctx)
        repo.audit_add(conn, "Backup downloaded", "", me["id"])
        conn.commit()
    return st


@app.post("/api/admin/restore")
def restore(body: StateBody, resp: Response, me=Depends(current_user)):
    _require_super(me)
    with repo.engine.connect() as conn:
        if repo.registered_companies(conn):
            raise HTTPException(409, "Other companies have registered on this server, and a restore would replace their data too.")
    _validate_state(body.state)
    auth = body.state.pop("_auth", None) or {}
    with repo.engine.begin() as conn:
        mine = get_pw_hash(conn, me["id"])
        legacy = repo.import_state(conn, body.state, me["id"])
        ids = {e["id"] for e in body.state["employees"]}
        for emp_id, h in legacy.items():
            set_pw_hash(conn, emp_id, h)
        for emp_id, a in auth.items():
            if emp_id in ids:
                if a.get("pw"):
                    set_pw_hash(conn, emp_id, a["pw"])
                if a.get("google"):
                    set_google_sub(conn, emp_id, a["google"])
        if me["id"] in ids and mine and not get_pw_hash(conn, me["id"]):
            set_pw_hash(conn, me["id"], mine)
        repo.audit_add(conn, "Backup restored", f"{len(ids)} employees", me["id"])
    end_session(resp)
    return {"ok": True}


@app.post("/api/admin/wipe")
def wipe(resp: Response, me=Depends(current_user)):
    _require_super(me)
    with repo.engine.connect() as conn:
        if repo.registered_companies(conn):
            raise HTTPException(409, "Other companies have registered on this server, and erasing would delete their data too.")
    with repo.engine.begin() as conn:
        repo.wipe(conn)
        # uploaded files go too (receipts, letters, TDS certificates, training content): nothing refers to them any more
        paths = [r[0] for r in conn.execute(text("SELECT path FROM files")).fetchall()]
        conn.execute(text("DELETE FROM files"))
    root = os.path.realpath(UPLOAD_DIR)
    for rel in paths:
        full = os.path.realpath(os.path.join(root, rel or ""))
        if full.startswith(root + os.sep) and os.path.isfile(full):
            try:
                os.remove(full)
            except OSError:
                log.warning("Could not delete %s", full)
    end_session(resp)
    log.warning("All data erased by %s", me.get("email"))
    return {"ok": True}


# ---------------------------------------------------------------- files (expense receipts and similar)
ALLOWED_MIME = ("image/", "application/pdf",
                # 2.16: documents shared in the knowledge hub
                "application/msword", "application/vnd.openxmlformats-officedocument.", "application/vnd.ms-excel",
                "application/vnd.ms-powerpoint", "text/plain", "text/csv")
# Never stored: an SVG (or HTML) opened from this site could run scripts in the user's session
BLOCKED_MIME = ("image/svg+xml", "text/html", "application/xhtml+xml")


def _store_file(data: bytes, filename: str, mime: str, company_id, owner_emp) -> str:
    fid = uuid.uuid4().hex
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", filename or "file")[-100:]
    sub = os.path.join(UPLOAD_DIR, fid[:2])
    os.makedirs(sub, exist_ok=True)
    path = os.path.join(sub, f"{fid}_{safe}")
    with open(path, "wb") as fh:
        fh.write(data)
    with repo.engine.begin() as conn:
        conn.execute(text("INSERT INTO files (id, name, mime, size, path, company_id, owner_emp, created_at) VALUES (:i, :n, :m, :s, :p, :c, :o, :t)"),
                     {"i": fid, "n": (filename or "file")[:255], "m": mime, "s": len(data), "p": os.path.relpath(path, UPLOAD_DIR), "c": company_id, "o": owner_emp, "t": int(time.time() * 1000)})
    return fid


def _read_file(conn, fid: str) -> bytes:
    r = conn.execute(text("SELECT path FROM files WHERE id=:i"), {"i": fid}).fetchone()
    root = os.path.realpath(UPLOAD_DIR)
    p = os.path.realpath(os.path.join(root, r.path)) if r else ""
    if not r or not p.startswith(root + os.sep) or not os.path.isfile(p):
        raise HTTPException(404, "The template file is missing on the server. Upload it again.")
    with open(p, "rb") as fh:
        return fh.read()


@app.post("/api/files")
async def upload_file(file: UploadFile = File(...), me=Depends(current_user)):
    data = await file.read()
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"Files can be up to {MAX_UPLOAD_MB} MB.")
    mime = (file.content_type or "application/octet-stream").lower()
    if mime.startswith(BLOCKED_MIME) or (file.filename or "").lower().endswith((".svg", ".svgz", ".html", ".htm")):
        raise HTTPException(400, "This kind of file cannot be attached. Use a photo, a PDF or an Office document.")
    if not mime.startswith(ALLOWED_MIME):
        raise HTTPException(400, "Attach a photo, a PDF or an Office document.")
    fid = _store_file(data, file.filename, mime, me.get("companyId"), me["id"])
    return {"id": fid, "name": file.filename, "size": len(data), "mime": mime}


@app.get("/api/files/{fid}")
def get_file(fid: str, me=Depends(current_user)):
    with repo.engine.connect() as conn:
        r = conn.execute(text("SELECT name, mime, path, company_id, owner_emp FROM files WHERE id=:i"), {"i": fid}).fetchone()
        if not r:
            raise HTTPException(404, "File not found")
        allowed = r.owner_emp == me["id"] or (me.get("role") == "super" and r.company_id not in repo.registered_companies(conn)) or (me.get("role") == "hr" and r.company_id in {me.get("companyId"), *(me.get("hrCompanies") or [])})
        if not allowed:
            allowed = _file_visible(conn, fid, me)
        photo = _photo_company(conn, fid)
        if not allowed and photo:
            # 2.15: a profile photo is seen by everyone in the employee's company (the organisation chart)
            allowed = photo in {me.get("companyId"), *(me.get("hrCompanies") or [])} or (me.get("role") == "super" and photo not in repo.registered_companies(conn))
    if not allowed:
        raise HTTPException(403, "You cannot open this file.")
    root = os.path.realpath(UPLOAD_DIR)
    p = os.path.realpath(os.path.join(root, r.path))
    if not p.startswith(root + os.sep) or not os.path.isfile(p):
        raise HTTPException(404, "File not found")
    # private, no-store: on a shared computer the next person signing in must not get the file from the browser cache.
    # Photos may be kept for an hour (a new photo is a new file), so the organisation chart does not fetch them each time.
    cache = "private, max-age=3600" if photo else "private, no-store"
    # nosniff: the browser keeps to the stored type; anything that is not a picture, a PDF or text is downloaded
    inline = str(r.mime or "").startswith(("image/", "application/pdf", "text/plain")) and not str(r.mime).startswith(BLOCKED_MIME)
    return FileResponse(p, media_type=r.mime, filename=r.name, content_disposition_type="inline" if inline else "attachment",
                        headers={"Cache-Control": cache, "X-Content-Type-Options": "nosniff"})


def _photo_company(conn, fid: str):
    """The company of the employee whose profile photo this file is, or None."""
    return conn.execute(text("SELECT company_id FROM employees WHERE JSON_UNQUOTE(JSON_EXTRACT(data, '$.photoId'))=:f LIMIT 1"), {"f": fid}).scalar()


def _file_visible(conn, fid: str, me: dict) -> bool:
    """Besides the uploader and HR: the employee for letters on their own record, the people taking part in a
    claim or request, and for leave the employee, their reporting line and the workflow approvers."""
    hit = lambda table, extra="": conn.execute(text(f"SELECT emp_id, data FROM {table} WHERE JSON_SEARCH(data, 'one', :f) IS NOT NULL {extra}"), {"f": fid}).fetchall()  # noqa: E731
    if conn.execute(text("SELECT 1 FROM employees WHERE id=:i AND JSON_SEARCH(data, 'one', :f) IS NOT NULL"), {"i": me["id"], "f": fid}).fetchone():
        return True
    for table in ("expense_claims", "approval_requests"):
        if any(me["id"] in (repo.loads(d).get("participants") or []) or emp == me["id"] for emp, d in hit(table)):
            return True
    if "finance" in (me.get("teams") or []):     # finance checks the receipts of every claim in its company
        if any(repo.loads(d).get("companyId") == me.get("companyId") and repo.loads(d).get("status") != "draft" for _e, d in hit("expense_claims")):
            return True
    # 2.11: evidence on goals (the employee and their managers) and files on performance meetings (those who see them)
    g_rows, m_rows = hit("goals"), hit("performance_meetings")
    if g_rows or m_rows:
        ctx = policy.make_ctx(me, repo.employees_index(conn), repo.registered_companies(conn))
        if any(emp == me["id"] or emp in ctx.line for emp, _d in g_rows):
            return True
        if any(perf.sees_meeting(repo.loads(d), me["id"], ctx.line) for _e, d in m_rows):
            return True
    # 2.16: files on posts of the news and knowledge hub, for the people the post goes to
    for _emp, d in hit("posts"):
        p = repo.loads(d)
        if p.get("status", "published") != "draft" and p.get("companyId") in {me.get("companyId"), *(me.get("hrCompanies") or [])} \
                and (not p.get("depts") or me.get("deptId") in p["depts"]) and (not p.get("locations") or me.get("locationId") in p["locations"]):
            return True
    # 2.18: a signed offer letter on an application, for the requisition's hiring manager and the person who raised it
    for _emp, d in hit("applications"):
        a = repo.loads(d)
        req = repo.get_records(conn, "reqs", [a.get("reqId")]).get(a.get("reqId")) or {}
        if me["id"] in {req.get("hiringMgr"), req.get("createdBy")} - {None, ""}:
            return True
    tr_rows = hit("trainings")
    for _emp, d in tr_rows:     # training content: the trainers and the people who attended
        t = repo.loads(d)
        if training.is_trainer(t, me["id"]) or conn.execute(text(
                "SELECT 1 FROM training_enrolments WHERE training_id=:t AND emp_id=:e AND status='attended'"), {"t": t.get("id"), "e": me["id"]}).fetchone():
            return True
    rows = hit("leave_requests")
    if rows:
        ctx = policy.make_ctx(me, repo.employees_index(conn), repo.registered_companies(conn))
        for emp, d in rows:
            rec = repo.loads(d)
            if emp == me["id"] or emp in ctx.line or any(me["id"] in (st or {}).get("approverIds", []) for st in rec.get("steps") or []):
                return True
    return False


# ---------------------------------------------------------------- 2.15: reimbursement runs (see reimb.py)
class ReimbRunBody(BaseModel):
    companyId: str
    claimIds: list[str] | None = None


class ReimbPaidBody(BaseModel):
    runId: str
    ref: str
    paidOn: str


def _reimb_ctx(conn, me, company_id):
    ctx = _ctx(conn, me)
    if not (ctx.is_hr_for(company_id) or ctx.is_finance_for(company_id)):
        raise HTTPException(403, "Only Finance or HR runs reimbursements.")
    return ctx


@app.post("/api/reimb/run")
def reimb_run(body: ReimbRunBody, me=Depends(current_user)):
    """Finance or HR: pays the approved claims now, in the company's reimbursement mode (Run now)."""
    with repo.engine.begin() as conn:
        ctx = _reimb_ctx(conn, me, body.companyId)
        co = repo.get_records(conn, "companies", [body.companyId]).get(body.companyId)
        if not co:
            raise HTTPException(404, "Company not found")
        run = reimb.make_run(conn, co, reimb._today(), by=me["id"], only=body.claimIds, not_of="" if ctx.is_hr_for(body.companyId) else me["id"])
        if not run:
            raise HTTPException(400, "No approved claims are waiting to be paid.")
        out = reimb.mails(conn, run, co) if (co.get("reimb") or {}).get("notify") and mailer.configured() else []
    for to, subj, text_ in out:
        try:
            mailer.send([to], subj, text_)
        except Exception as e:  # noqa: BLE001
            log.warning("Reimbursement mail to %s failed: %s", to, e)
    return {"run": run, "mailed": len(out)}


@app.post("/api/reimb/paid")
def reimb_paid(body: ReimbPaidBody, me=Depends(current_user)):
    """Finance or HR: the bank transfer of a run is made; its claims are paid."""
    with repo.engine.begin() as conn:
        run = repo.get_records(conn, "reimbRuns", [body.runId]).get(body.runId)
        if not run:
            raise HTTPException(404, "Run not found")
        _reimb_ctx(conn, me, run.get("companyId"))
        try:
            run = reimb.mark_paid(conn, run, body.ref, body.paidOn, me["id"])
        except reimb.Problem as e:
            raise HTTPException(400, str(e)) from None
    return {"run": run}


class NotifyBody(BaseModel):
    requestId: str
    event: str            # submitted | decided


STAT_LABELS = {"pan": "PAN", "aadhaar": "Aadhaar", "uan": "UAN (PF)", "pfNo": "PF member ID", "esiNo": "ESI IP number", "esiDispensary": "ESI dispensary"}


@app.post("/api/notify")
def notify(body: NotifyBody, me=Depends(current_user)):
    """E-mails about a statutory details request: to HR when an employee submits one, and to the employee
    when HR decides. Only the requester can announce a submission and only HR a decision."""
    with repo.engine.begin() as conn:
        row = conn.execute(text("SELECT data FROM approval_requests WHERE id=:i"), {"i": body.requestId}).fetchone()
        if not row:
            raise HTTPException(404, "That request is not saved yet.")
        r = repo.loads(row[0])
        if r.get("kind") != "statutory":
            raise HTTPException(400, "E-mail is sent only for statutory detail requests.")
        emps = repo.employees_index(conn)
        emp = emps.get(r.get("empId")) or {}
        co = r.get("companyId")
        name = f"{emp.get('firstName', '')} {emp.get('lastName', '')}".strip()
        private = repo.registered_companies(conn)
        is_hr = (me.get("role") == "super" and co not in private) or (me.get("role") == "hr" and co in {me.get("companyId"), *(me.get("hrCompanies") or [])})
        if body.event == "submitted":
            if r.get("by") != me["id"]:
                raise HTTPException(403, "Only the person who raised the request can announce it.")
            to = [e.get("email") for e in emps.values() if e.get("status") != "exited" and e.get("id") != me["id"] and (
                (e.get("role") == "super" and co not in private) or (e.get("role") == "hr" and co in {e.get("companyId"), *(e.get("hrCompanies") or [])}))]
            mask = lambda k, v: ("XXXX XXXX " + str(v)[-4:]) if k == "aadhaar" and v else (v or "—")  # noqa: E731
            lines = [f"- {STAT_LABELS.get(k, k)}: {mask(k, (r.get('old') or {}).get(k))} -> {mask(k, v)}" for k, v in (r.get("changes") or {}).items()]
            subject, text_ = email_templates.render(conn, co, "statutory.submitted", {
                "name": name, "no": r.get("no"), "changesLines": "\n".join(lines), "docCount": len(r.get("documents") or []),
                "noteLine": f"\nNote: {r.get('reason')}" if r.get("reason") else "", "link": f"{APP_URL}/#/request/{r['id']}"})
        elif body.event == "decided":
            if not is_hr:
                raise HTTPException(403, "Only HR can announce a decision.")
            to = [emp.get("email")]
            ok = r.get("status") == "applied"
            note = next((st.get("note") for st in reversed(r.get("steps") or []) if st.get("decision")), "")
            subject, text_ = email_templates.render(conn, co, "statutory.decided", {
                "firstName": emp.get("firstName", ""), "outcome": "approved" if ok else "not approved", "no": r.get("no"),
                "changeLabels": ", ".join(STAT_LABELS.get(k, k) for k in (r.get("changes") or {})),
                "noteBlock": f"\n\nNote from HR: {note}" if note else "", "link": f"{APP_URL}/#/request/{r['id']}"})
        else:
            raise HTTPException(400, "Unknown event.")
        to = [t for t in to if t]
        if not mailer.configured():
            return {"sent": False, "reason": "e-mail is not set up on the server; HR sees it in Approvals"}
        if not to:
            return {"sent": False, "reason": "no e-mail address to send to"}
        key = f"{r['id']}:{body.event}"
        if conn.execute(text("SELECT 1 FROM audit_log WHERE what='E-mail sent' AND detail=:d"), {"d": key}).fetchone():
            return {"sent": False, "reason": "e-mail was already sent"}
        try:
            mailer.send(to, subject, text_)
        except Exception as e:  # noqa: BLE001
            log.warning("Mail failed: %s", e)
            return {"sent": False, "reason": "the e-mail server refused the message; HR sees it in Approvals"}
        repo.audit_add(conn, "E-mail sent", key, me["id"], module="approvals", ref_type="employee", ref_id=r.get("empId"))
        return {"sent": True, "to": f"{len(to)} recipient{'s' if len(to) > 1 else ''}"}


class CompNotifyBody(BaseModel):
    cycleId: str
    poolId: str = ""
    event: str            # launched | submitted | decided | comment


@app.post("/api/comp/notify")
def comp_notify(body: CompNotifyBody, me=Depends(current_user)):
    """E-mails for salary planning. Recipients are worked out here from the saved budget, never taken from the
    browser: the next approver when a budget is submitted, the holder (and the next approver) after a decision,
    everyone on the budget for a comment, and every budget holder when HR opens planning."""
    with repo.engine.begin() as conn:
        emps = repo.employees_index(conn)
        ctx = policy.make_ctx(me, emps, repo.registered_companies(conn))
        cycle = repo.get_records(conn, "compCycles", [body.cycleId]).get(body.cycleId)
        if not cycle:
            raise HTTPException(404, "That salary plan is not saved yet.")
        pools = repo.records_where(conn, "compBudgets", "cycle_id", body.cycleId)
        co = cycle.get("companyId")
        hr_ids = [e["id"] for e in emps.values() if e.get("status") != "exited" and (
            (e.get("role") == "super" and co not in ctx.private) or (e.get("role") == "hr" and co in {e.get("companyId"), *(e.get("hrCompanies") or [])}))]
        nm = lambda i: f"{(emps.get(i) or {}).get('firstName', '')} {(emps.get(i) or {}).get('lastName', '')}".strip()  # noqa: E731
        link = f"{APP_URL}/#/compplan?c={cycle['id']}"
        if body.event == "launched":
            if not ctx.is_hr_for(co):
                raise HTTPException(403, "Only HR opens salary planning.")
            to_ids = [p.get("empId") for p in pools]
            subject, text_ = email_templates.render(conn, co, "comp.launched", {
                "cycleName": cycle.get("name", ""), "deadlineBlock": f" by {cycle['deadline']}" if cycle.get("deadline") else "",
                "effective": cycle.get("effective", ""), "link": link})
        else:
            pool = next((p for p in pools if p.get("id") == body.poolId), None)
            if not pool:
                raise HTTPException(404, "That budget is not saved yet.")
            holder = pool.get("empId")
            if not (ctx.is_hr_for(co) or holder == me["id"] or holder in ctx.line):
                raise HTTPException(403, "You are not taking part in this budget.")
            steps = pool.get("steps") or []
            nxt = next((s for s in steps if not s.get("decision")), None)
            next_ids = (hr_ids if nxt and nxt.get("kind") == "hr" else list((nxt or {}).get("approverIds") or [])) if pool.get("status") == "submitted" else []
            who = nm(holder)
            if body.event == "submitted":
                if holder != me["id"] and not ctx.is_hr_for(co):
                    raise HTTPException(403, "Only the budget holder submits it.")
                to_ids = next_ids
                subject, text_ = email_templates.render(conn, co, "comp.submitted",
                                                         {"who": who, "cycleName": cycle.get("name", ""), "link": f"{link}&p={pool['id']}"})
            elif body.event == "decided":
                last = next((s for s in reversed(steps) if s.get("decision")), None)
                if not last or last.get("by") != me["id"]:
                    raise HTTPException(403, "Only the person who decided can announce it.")
                ok = last.get("decision") == "approved"
                to_ids = [holder] + (next_ids if ok else [])
                subject, text_ = email_templates.render(conn, co, "comp.decided", {
                    "who": who, "outcome": "approved" if ok else "sent back", "outcomeVerb": "approved" if ok else "sent back for changes",
                    "deciderName": nm(me["id"]), "cycleName": cycle.get("name", ""), "noteBlock": f"\n\nNote: {last.get('note')}" if last.get("note") else "",
                    "link": f"{link}&p={pool['id']}"})
            elif body.event == "comment":
                c = (pool.get("comments") or [None])[-1]
                if not c or c.get("by") != me["id"]:
                    raise HTTPException(403, "Only the writer can announce a comment.")
                to_ids = [holder] + [i for s in steps for i in (s.get("approverIds") or [])] + [p.get("empId") for p in pools if p.get("id") == pool.get("parentId")]
                if nxt and nxt.get("kind") == "hr":
                    to_ids += hr_ids
                subject, text_ = email_templates.render(conn, co, "comp.comment",
                                                         {"who": who, "writerName": nm(me["id"]), "commentText": c.get("text", ""), "link": f"{link}&p={pool['id']}"})
            else:
                raise HTTPException(400, "Unknown event.")
        to = [(emps.get(i) or {}).get("email") for i in dict.fromkeys(to_ids) if i and i != me["id"] and (emps.get(i) or {}).get("status") != "exited"]
        to = [t for t in to if t]
        if not mailer.configured():
            return {"sent": False, "reason": "e-mail is not set up on the server; it shows in Approvals"}
        if not to:
            return {"sent": False, "reason": "no e-mail address to send to"}
        try:
            mailer.send(to, subject, text_)
        except Exception as e:  # noqa: BLE001
            log.warning("Mail failed: %s", e)
            return {"sent": False, "reason": "the e-mail server refused the message; it shows in Approvals"}
        repo.audit_add(conn, "E-mail sent", f"comp:{body.cycleId}:{body.poolId}:{body.event}", me["id"], module="compensation", ref_type="comp", ref_id=body.cycleId)
        return {"sent": True, "to": f"{len(to)} recipient{'s' if len(to) > 1 else ''}"}


# ---------------------------------------------------------------- 2.18: recruitment flow e-mails
class RecruitNotifyBody(BaseModel):
    event: str                      # shortlist | selection | referral
    appIds: list[str] = []
    interviewId: str = ""
    referralId: str = ""


def _inr(n) -> str:
    """12,34,567 (Indian grouping)."""
    try:
        s = str(int(round(float(n or 0))))
    except (TypeError, ValueError):
        return "—"
    head, tail = s[:-3], s[-3:]
    while len(head) > 2:
        tail, head = head[-2:] + "," + tail, head[:-2]
    return (head + "," + tail) if head else tail


@app.post("/api/recruit/notify")
def recruit_notify(body: RecruitNotifyBody, me=Depends(current_user)):
    """E-mails in the recruitment flow, worked out from the saved records (never from what the browser says):
    a shortlist to each approver who has not decided, a final-selection proposal to the hiring manager, and a
    referral to the person referred to. Sent only by the person who made the shortlist, proposal or referral."""
    with repo.engine.begin() as conn:
        emps = repo.employees_index(conn)
        nm = lambda i: f"{(emps.get(i) or {}).get('firstName', '')} {(emps.get(i) or {}).get('lastName', '')}".strip()  # noqa: E731
        mails: list[tuple[str, str, str]] = []          # (employee id, subject, text)
        if body.event in ("shortlist", "selection"):
            apps = list(repo.get_records(conn, "apps", body.appIds[:200]).values())
            reqs = {a.get("reqId") for a in apps}
            if not apps or len(reqs) != 1:
                raise HTTPException(400, "Send one requisition's candidates at a time.")
            req = repo.get_records(conn, "reqs", list(reqs)).get(next(iter(reqs))) or {}
            co = req.get("companyId")
            cands = repo.get_records(conn, "cands", [a.get("candId") for a in apps])
            base = {"sender": nm(me["id"]), "job": req.get("title", ""), "reqNo": req.get("no", "")}
            if body.event == "shortlist":
                apps = [a for a in apps if (a.get("shortlist") or {}).get("status") == "pending" and a["shortlist"].get("by") == me["id"]]
                if not apps:
                    raise HTTPException(400, "None of these candidates is waiting for approval on a shortlist you sent.")

                def line(a):
                    c = cands.get(a.get("candId")) or {}
                    now = f", {c.get('currentTitle')} at {c.get('currentCompany') or '—'}" if c.get("currentTitle") else ""
                    return f"- {c.get('name', '')}: {c.get('expYears') or 0} years{now}, expects {_inr(c.get('expectedCtc'))}"
                note = next((a["shortlist"].get("note") for a in apps if a["shortlist"].get("note")), "")
                to_ids = list(dict.fromkeys(x.get("id") for a in apps for x in a["shortlist"].get("approvers") or [] if not x.get("decision")))
                for i in to_ids:
                    mine = [a for a in apps if any(x.get("id") == i and not x.get("decision") for x in a["shortlist"].get("approvers") or [])]
                    subject, text_ = email_templates.render(conn, co, "recruit.shortlist", {
                        **base, "firstName": (emps.get(i) or {}).get("firstName", ""), "count": len(mine), "candidatesLines": "\n".join(line(a) for a in mine),
                        "noteBlock": f"Note: {note}\n" if note else "", "link": f"{APP_URL}/#/slapprove?req={req.get('id')}"})
                    mails.append((i, subject, text_))
            else:
                apps = [a for a in apps if (a.get("sel") or {}).get("status") == "proposed" and a["sel"].get("by") == me["id"]]
                mgr = req.get("hiringMgr")
                if not apps or not mgr or mgr == me["id"]:
                    raise HTTPException(400, "Nothing here is waiting for the hiring manager's decision.")
                word = {"select": "select", "reject": "reject", "hold": "keep on hold"}
                lines = [f"- {(cands.get(a.get('candId')) or {}).get('name', '')}: {word.get(a['sel'].get('proposed'), '')}"
                         f"{' (rank ' + str(a['sel'].get('rank')) + ')' if a['sel'].get('rank') else ''}" for a in apps]
                subject, text_ = email_templates.render(conn, co, "recruit.selection", {
                    **base, "firstName": (emps.get(mgr) or {}).get("firstName", ""), "candidatesLines": "\n".join(lines),
                    "link": f"{APP_URL}/#/finalsel/{req.get('id')}"})
                mails.append((mgr, subject, text_))
        elif body.event == "referral":
            iv = repo.get_records(conn, "interviews", [body.interviewId]).get(body.interviewId) or {}
            ref = next((x for x in iv.get("referrals") or [] if x.get("id") == body.referralId), None)
            if not ref or ref.get("by") != me["id"] or ref.get("decision"):
                raise HTTPException(400, "That referral is not saved, is not yours, or is answered.")
            app_ = repo.get_records(conn, "apps", [iv.get("appId")]).get(iv.get("appId")) or {}
            req = repo.get_records(conn, "reqs", [app_.get("reqId")]).get(app_.get("reqId")) or {}
            cand = repo.get_records(conn, "cands", [app_.get("candId")]).get(app_.get("candId")) or {}
            co = req.get("companyId")
            subject, text_ = email_templates.render(conn, co, "recruit.referral", {
                "firstName": (emps.get(ref.get("to")) or {}).get("firstName", ""), "sender": nm(me["id"]), "candidate": cand.get("name", ""),
                "job": req.get("title", ""), "round": iv.get("round", ""), "questionBlock": f"\n\nQuestion: {ref['question']}" if ref.get("question") else "",
                "link": f"{APP_URL}/#/app/{app_.get('id')}"})
            mails.append((ref.get("to"), subject, text_))
        else:
            raise HTTPException(400, "Unknown event.")
        private = repo.registered_companies(conn)
        def _for_co(i):   # only people who can act for the requisition's company are e-mailed about its candidates
            e = emps.get(i) or {}
            return e.get("companyId") == co or co in (e.get("hrCompanies") or []) or (e.get("role") == "super" and co not in private)
        mails = [(i, s, t) for i, s, t in mails if i and i != me["id"] and _for_co(i) and (emps.get(i) or {}).get("email") and (emps.get(i) or {}).get("status") != "exited"]
        if not mailer.configured():
            return {"sent": False, "reason": "e-mail is not set up on the server; it shows in their Approvals"}
        if not mails:
            return {"sent": False, "reason": "no e-mail address to send to; it shows in their Approvals"}
        sent = 0
        for i, subject, text_ in mails:
            try:
                mailer.send([emps[i]["email"]], subject, text_)
                sent += 1
            except Exception as e:  # noqa: BLE001
                log.warning("Mail failed: %s", e)
        if not sent:
            return {"sent": False, "reason": "the e-mail server refused the message; it shows in their Approvals"}
        repo.audit_add(conn, "E-mail sent", f"recruit:{body.event}:{len(mails)}", me["id"], module="recruitment")
        return {"sent": True, "to": f"{sent} recipient{'s' if sent > 1 else ''}"}


# ---------------------------------------------------------------- 2.19: the candidate portal and the conversation
class CandOfferBody(BaseModel):
    appId: str
    action: str                          # accept | decline | negotiate
    letterNo: str
    name: str = ""
    agree: bool = False
    reason: str = ""
    askCtc: str | float | None = None
    askDoj: str = ""
    askBonus: str | float | None = None
    askOther: str = ""
    note: str = ""
    file: dict | None = None             # the signed copy: {name, type, data (a data: URL)}


class CandMsgBody(BaseModel):
    text: str = ""
    subject: str = ""
    appId: str = ""
    files: list[dict] = Field(default_factory=list)


class HrMsgBody(BaseModel):
    candId: str
    appId: str = ""
    subject: str = ""
    text: str = ""
    fileIds: list[str] = Field(default_factory=list)


class CandNotifyBody(BaseModel):
    event: str                           # interview | offer | nego
    appId: str
    interviewId: str = ""
    roundId: str = ""


class CandIdBody(BaseModel):
    candId: str


class InboxBody(BaseModel):
    on: bool = False
    host: str = ""
    port: int = 993
    security: str = "ssl"                # ssl | starttls | none
    auth: str = "password"               # password | m365
    user: str = ""
    password: str = ""                   # empty keeps the saved one
    folder: str = "INBOX"
    address: str = ""


def _rupees(n) -> str:
    return f"₹ {_inr(n)}"


def _cp(fn, *args, **kw):
    try:
        return fn(*args, **kw)
    except cportal.Problem as e:
        raise HTTPException(400, str(e)) from None


def _names(conn) -> dict:
    return {i: f"{e.get('firstName', '')} {e.get('lastName', '')}".strip() for i, e in repo.employees_index(conn).items()}


def _upload_from_candidate(f: dict | None, cand: dict):
    """A file the candidate attached (a data: URL), kept as theirs. Returns {id, name, size, mime} or None."""
    if not f:
        return None
    m = re.match(r"^data:([\w./+-]+);base64,(.+)$", str(f.get("data") or ""), re.S)
    if not m:
        raise HTTPException(400, "The file could not be read.")
    mime = m.group(1).lower()
    if mime not in cportal.FILE_MIME:
        raise HTTPException(400, "Attach a PDF, a photo or a Word document.")
    try:
        data = base64.b64decode(m.group(2), validate=False)
    except ValueError:
        raise HTTPException(400, "The file could not be read.") from None
    if not data or len(data) > cportal.FILE_MB * 1024 * 1024:
        raise HTTPException(400, f"A file can be up to {cportal.FILE_MB} MB.")
    name = re.sub(r"[\\/]", "_", str(f.get("name") or "file"))[:120]
    return {"id": _store_file(data, name, mime, cand.get("companyId"), candform.SESSION_PREFIX + cand["id"]), "name": name, "size": len(data), "mime": mime}


def _cand_view(conn, cand: dict) -> dict:
    names = _names(conn)
    co = repo.get_records(conn, "companies", [cand.get("companyId")]).get(cand.get("companyId")) or {}
    apps = []
    for a in sorted(repo.records_where(conn, "apps", "cand_id", cand["id"]), key=lambda x: x.get("createdAt") or 0, reverse=True):
        r = repo.get_records(conn, "reqs", [a.get("reqId")]).get(a.get("reqId"))
        if not r:
            continue
        ivs = sorted(repo.records_where(conn, "interviews", "app_id", a["id"]), key=lambda i: (i.get("date") or "", i.get("start") or ""))
        st = cportal.status_of(a, ivs)
        loc = repo.get_records(conn, "locations", [r.get("locationId")]).get(r.get("locationId")) or {}
        apps.append({"id": a["id"], "job": r.get("title", ""), "reqNo": r.get("no", ""), "location": loc.get("name", ""), "appliedAt": a.get("createdAt"),
                     "status": st, "steps": cportal.steps_of(st), "interviews": [cportal.interview_view(i, names) for i in ivs], "offer": cportal.offer_view(a)})
    msgs = [cportal.message_view(m, names) for m in cand.get("msgs") or []]
    return {"name": cand.get("name", ""), "company": co.get("legalName") or co.get("name", ""), "login": candform.login_name(cand),
            "applications": apps, "messages": msgs, "unread": sum(1 for m in msgs if m["dir"] == "out" and not m["read"]),
            "formStatus": (cand.get("form") or {}).get("status", ""), "mailOn": mailer.configured(), "hasEmail": bool(cand.get("email"))}


def _hr_for_cand(conn, me: dict, cand: dict) -> bool:
    """HR of the candidate's company, or the hiring manager or raiser of one of the candidate's requisitions."""
    if _ctx(conn, me).is_hr_for(cand.get("companyId")):
        return True
    for a in repo.records_where(conn, "apps", "cand_id", cand["id"]):
        r = repo.get_records(conn, "reqs", [a.get("reqId")]).get(a.get("reqId")) or {}
        if me["id"] in {r.get("hiringMgr"), r.get("createdBy")}:
            return True
    return False


@app.get("/api/candidate/portal")
def candidate_portal(cand=Depends(current_candidate)):
    with repo.engine.connect() as conn:
        return _cand_view(conn, cand)


@app.post("/api/candidate/offer")
def candidate_offer(body: CandOfferBody, request: Request, cand=Depends(current_candidate)):
    """The candidate accepts the offer (typed signature, and the signed copy if they have one), declines it, or asks
    for changes. It happens at once: the application changes and HR is told."""
    time.sleep(0.1)
    signed = _upload_from_candidate(body.file, cand) if body.action == "accept" else None
    with repo.engine.begin() as conn:
        cand = repo.get_records(conn, "cands", [cand["id"]]).get(cand["id"])
        a = repo.get_records(conn, "apps", [body.appId]).get(body.appId)
        if not a or a.get("candId") != cand["id"]:
            raise HTTPException(404, "That application was not found.")
        r = repo.get_records(conn, "reqs", [a.get("reqId")]).get(a.get("reqId")) or {}
        o = a.get("offer") or {}
        if body.action == "accept":
            _cp(cportal.accept, a, body.letterNo, body.name, body.agree, cand.get("name", ""), request.client.host if request.client else "", signed)
            subj, txt = "I accept the offer", (f"I accept the offer {o.get('letterNo')}: {_rupees(o.get('ctc'))} a year, joining on {cportal._dmy(o.get('doj'))}. "
                                               f"Signed: {a['offer']['signed']['esign']['name']}." + (" The signed copy is attached." if signed else ""))
            what = "Candidate accepted the offer online"
        elif body.action == "decline":
            _cp(cportal.decline, a, body.letterNo, body.reason)
            subj, txt, what = "I decline the offer", f"I decline the offer {o.get('letterNo')}. {body.reason.strip()}", "Candidate declined the offer online"
        elif body.action == "negotiate":
            row = _cp(cportal.negotiate, a, body.letterNo, body.model_dump())
            subj = "About my offer"
            txt = f"About the offer {o.get('letterNo')}, I would like: {cportal.describe_ask(row, _rupees)}." + (f"\n\n{row['note']}" if row.get("note") else "")
            what = "Candidate asked for changes to the offer"
        else:
            raise HTTPException(400, "Unknown action.")
        repo.upsert(conn, "apps", [a], None)
        m = cportal.add_message(cand, direction="in", by="cand", text_=txt, subject=subj, via="portal", app_id=a["id"], job=r.get("title", ""),
                                files=[signed] if signed else [])
        repo.upsert(conn, "cands", [cand], None)
        repo.audit_add(conn, what, f"{cand.get('name', '')}, {r.get('no', '')}", None, module="recruitment", ref_type="candidate", ref_id=cand["id"])
        repo.bump_rev(conn)
        cmail.to_hr(conn, cand, m)
        return _cand_view(conn, cand)


@app.post("/api/candidate/message")
def candidate_message(body: CandMsgBody, cand=Depends(current_candidate)):
    if len(body.files) > cportal.FILES_MAX:
        raise HTTPException(400, f"Attach up to {cportal.FILES_MAX} files.")
    hour = cportal.now_ms() - 3600 * 1000
    if sum(1 for m in cand.get("msgs") or [] if m.get("dir") == "in" and (m.get("at") or 0) > hour) >= 30:
        raise HTTPException(429, "You have sent many messages in the last hour. Please wait a little.")
    files = [_upload_from_candidate(f, cand) for f in body.files]
    with repo.engine.begin() as conn:
        cand = repo.get_records(conn, "cands", [cand["id"]]).get(cand["id"])
        job = ""
        if body.appId:
            a = repo.get_records(conn, "apps", [body.appId]).get(body.appId) or {}
            if a.get("candId") == cand["id"]:
                job = (repo.get_records(conn, "reqs", [a.get("reqId")]).get(a.get("reqId")) or {}).get("title", "")
        m = _cp(cportal.add_message, cand, direction="in", by="cand", text_=body.text, subject=body.subject, via="portal", app_id=body.appId if job else "",
                job=job or cmail.job_of(conn, cand), files=files)
        cportal.mark_read(cand, "out")
        repo.upsert(conn, "cands", [cand], None)
        repo.audit_add(conn, "Message from the candidate", cand.get("name", ""), None, module="recruitment", ref_type="candidate", ref_id=cand["id"])
        repo.bump_rev(conn)
        cmail.to_hr(conn, cand, m)
        return _cand_view(conn, cand)


@app.post("/api/candidate/messages/read")
def candidate_messages_read(cand=Depends(current_candidate)):
    with repo.engine.begin() as conn:
        cand = repo.get_records(conn, "cands", [cand["id"]]).get(cand["id"])
        if cportal.mark_read(cand, "out"):
            repo.upsert(conn, "cands", [cand], None)
            repo.bump_rev(conn)
    return {"ok": True}


@app.get("/api/candidate/files/{fid}")
def candidate_file(fid: str, cand=Depends(current_candidate)):
    """A file in the candidate's messages (theirs or HR's), or their signed offer letter."""
    with repo.engine.connect() as conn:
        r = conn.execute(text("SELECT name, mime, path, owner_emp FROM files WHERE id=:i"), {"i": fid}).fetchone()
        mine = {f.get("id") for m in cand.get("msgs") or [] for f in m.get("files") or []}
        mine |= {((a.get("offer") or {}).get("signed") or {}).get("fileId") for a in repo.records_where(conn, "apps", "cand_id", cand["id"])}
        if not r or not (fid in mine or r.owner_emp == candform.SESSION_PREFIX + cand["id"]):
            raise HTTPException(404, "File not found")
    root = os.path.realpath(UPLOAD_DIR)
    p = os.path.realpath(os.path.join(root, r.path))
    if not p.startswith(root + os.sep) or not os.path.isfile(p):
        raise HTTPException(404, "File not found")
    inline = str(r.mime or "").startswith(("image/", "application/pdf"))
    return FileResponse(p, media_type=r.mime, filename=r.name, content_disposition_type="inline" if inline else "attachment",
                        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


@app.post("/api/recruit/message", dependencies=[Depends(require_csrf)])
def recruit_message(body: HrMsgBody, me=Depends(current_user)):
    """HR (or the hiring manager) writes to a candidate: kept in the thread, shown in the candidate's portal and
    e-mailed to them."""
    with repo.engine.begin() as conn:
        cand = repo.get_records(conn, "cands", [body.candId]).get(body.candId)
        if not cand or not _hr_for_cand(conn, me, cand):
            raise HTTPException(403, "Only HR and the hiring manager write to this candidate.")
        files = []
        for fid in body.fileIds[:cportal.FILES_MAX]:
            f = conn.execute(text("SELECT name, mime, size, owner_emp FROM files WHERE id=:i"), {"i": fid}).fetchone()
            if not f or f.owner_emp != me["id"]:
                raise HTTPException(400, "Attach files you uploaded just now.")
            files.append({"id": fid, "name": f.name, "size": f.size, "mime": f.mime})
        job = ""
        if body.appId:
            a = repo.get_records(conn, "apps", [body.appId]).get(body.appId) or {}
            job = (repo.get_records(conn, "reqs", [a.get("reqId")]).get(a.get("reqId")) or {}).get("title", "") if a.get("candId") == cand["id"] else ""
        m = _cp(cportal.add_message, cand, direction="out", by=me["id"], text_=body.text, subject=body.subject, via="app",
                app_id=body.appId if job else "", job=job or cmail.job_of(conn, cand), files=files)
        cportal.mark_read(cand, "in")
        repo.upsert(conn, "cands", [cand], me["id"])
        repo.audit_add(conn, "Message to the candidate", cand.get("name", ""), me["id"], module="recruitment", ref_type="candidate", ref_id=cand["id"])
        repo.bump_rev(conn)
        why = cmail.to_candidate(conn, cand, m)
    return {"ok": True, "emailed": not why, "reason": why}


@app.post("/api/recruit/messages/read", dependencies=[Depends(require_csrf)])
def recruit_messages_read(body: CandIdBody, me=Depends(current_user)):
    with repo.engine.begin() as conn:
        cand = repo.get_records(conn, "cands", [body.candId]).get(body.candId)
        if not cand or not _hr_for_cand(conn, me, cand):
            raise HTTPException(403, "Not your candidate.")
        if cportal.mark_read(cand, "in"):
            repo.upsert(conn, "cands", [cand], me["id"])
            repo.bump_rev(conn)
    return {"ok": True}


@app.post("/api/recruit/candnotify", dependencies=[Depends(require_csrf)])
def recruit_candnotify(body: CandNotifyBody, me=Depends(current_user)):
    """A notice to the candidate after a step (interview scheduled, moved or cancelled; offer issued; negotiation
    answered), written from the saved records, kept in the thread and e-mailed. Each notice is sent once."""
    with repo.engine.begin() as conn:
        a = repo.get_records(conn, "apps", [body.appId]).get(body.appId)
        cand = repo.get_records(conn, "cands", [(a or {}).get("candId")]).get((a or {}).get("candId")) if a else None
        if not a or not cand or not _hr_for_cand(conn, me, cand):
            raise HTTPException(403, "Not your candidate.")
        r = repo.get_records(conn, "reqs", [a.get("reqId")]).get(a.get("reqId")) or {}
        co = cand.get("companyId")
        names = _names(conn)
        if body.event == "interview":
            i = repo.get_records(conn, "interviews", [body.interviewId]).get(body.interviewId)
            if not i or i.get("appId") != a["id"]:
                raise HTTPException(404, "Interview not found.")
            key = f"iv:{i['id']}:{i.get('status')}:{i.get('date')}:{i.get('start')}"
            before = any(str(m.get("key", "")).startswith(f"iv:{i['id']}:") for m in cand.get("msgs") or [])
            gone = i.get("status") == "cancelled"
            if i.get("status") not in ("scheduled", "cancelled"):
                return {"ok": True, "skipped": True}
            where = {"video": f"Video call: {i.get('link') or 'the link will follow'}", "phone": "By phone: we will call you on your mobile.",
                     "f2f": f"In person: {i.get('venue') or 'the venue will follow'}"}.get(i.get("mode"), "")
            panel = [names.get(p) for p in i.get("panel") or [] if names.get(p)]
            subject, txt = email_templates.render(conn, co, "candidate.notice.interview", {
                "headline": "Interview cancelled" if gone else "Interview moved" if before else "Interview", "job": r.get("title", ""), "round": i.get("round") or "Interview",
                "intro": f"Your {str(i.get('round') or 'interview').lower()} for {r.get('title', '')} is cancelled. We will be in touch." if gone
                         else f"Your interview for {r.get('title', '')} has been moved. The new time:" if before else f"Your interview for {r.get('title', '')} is arranged.",
                "when": f"{cportal._dmy(i.get('date'))} at {i.get('start') or ''}", "duration": int(i.get("duration") or 45), "where": "" if gone else where,
                "panelLine": "" if gone or not panel else f"With {', '.join(panel[:-1]) + ' and ' + panel[-1] if len(panel) > 1 else panel[0]}.",
                "outro": "" if gone else "If the time does not suit you, reply to this message. You can also see it in your candidate portal."})
        elif body.event == "offer":
            o = a.get("offer") or {}
            if o.get("status") != "issued" or not o.get("letterNo"):
                raise HTTPException(400, "The offer is not issued.")
            key = f"offer:{o['letterNo']}"
            subject, txt = email_templates.render(conn, co, "candidate.notice.offer", {
                "job": r.get("title", ""), "roundWord": " (revised offer)" if o.get("versions") else "", "letterNo": o["letterNo"],
                "expiryLine": f" Please reply by {cportal._dmy(o.get('expiry'))}." if o.get("expiry") else ""})
        elif body.event == "nego":
            x = next((y for y in a.get("nego") or [] if y.get("id") == body.roundId and y.get("viaPortal")), None)
            if not x or x.get("outcome") == "open" or not x.get("answeredAt"):
                raise HTTPException(400, "That request is not answered yet.")
            key = f"nego:{x['id']}:{x['answeredAt']}"
            agreed = x.get("outcome") == "agreed"
            terms = cportal.describe_ask({"askCtc": x.get("ourCtc"), "askDoj": x.get("ourDoj"), "askBonus": x.get("ourBonus")}, _rupees) if agreed else ""
            subject = "About your request on the offer"
            txt = (x.get("answer") or "").strip() + (f"\n\nAgreed: {terms}. A revised offer letter will follow in your candidate portal." if agreed and terms else
                                                      "\n\nThe offer stands as issued. You can accept it, decline it or write to us in your candidate portal." if x.get("outcome") == "held" else "")
        else:
            raise HTTPException(400, "Unknown event.")
        m = cportal.add_message(cand, direction="out", by=me["id"], text_=txt.strip(), subject=subject, via="auto", app_id=a["id"], job=r.get("title", ""), key=key)
        if not m:
            return {"ok": True, "skipped": True}
        repo.upsert(conn, "cands", [cand], me["id"])
        repo.bump_rev(conn)
        why = cmail.to_candidate(conn, cand, m)
    return {"ok": True, "emailed": not why, "reason": why}


@app.get("/api/admin/mailin")
def mailin_get(me=Depends(current_user)):
    _require_super(me)
    with repo.engine.connect() as conn:
        return cmail.public(conn)


@app.post("/api/admin/mailin", dependencies=[Depends(require_csrf)])
def mailin_save(body: InboxBody, me=Depends(current_user)):
    _require_super(me)
    if body.security not in ("ssl", "starttls", "none") or body.auth not in ("password", "m365"):
        raise HTTPException(400, "Choose the security and the sign-in method.")
    if body.on:
        if not body.host.strip():
            raise HTTPException(400, "Enter the mail server that receives the replies (IMAP).")
        if not EMAIL.match(body.address.strip()):
            raise HTTPException(400, "Enter the address replies go to: the mailbox read here.")
        if body.auth == "m365" and not mailer.settings().get("clientId"):
            raise HTTPException(400, "Microsoft 365 sign-in uses the app set up for sending: set up sending with Microsoft 365 first.")
    with repo.engine.begin() as conn:
        old = cmail.stored(conn)
        d = {"on": body.on, "host": body.host.strip(), "port": int(body.port or 993), "security": body.security, "auth": body.auth, "user": body.user.strip(),
             "password": mailer.encrypt(body.password) if body.password else old.get("password", ""), "folder": body.folder.strip() or "INBOX",
             "address": body.address.strip(), "lastRun": old.get("lastRun"), "lastResult": old.get("lastResult", "")}
        if body.on and body.auth == "password" and not d["password"]:
            raise HTTPException(400, "Enter the mailbox password.")
        cmail.save(conn, d)
        repo.audit_add(conn, "Replies mailbox changed", d["address"] if body.on else "switched off", me["id"])
        return cmail.public(conn)


@app.post("/api/admin/mailin/check", dependencies=[Depends(require_csrf)])
def mailin_check(me=Depends(current_user)):
    _require_super(me)
    try:
        r = cmail.run_once(repo.engine, lambda data, name, mime, co, owner: _store_file(data, name, mime, co, owner))
    except Exception as e:  # noqa: BLE001 - shown to the administrator as it is
        raise HTTPException(502, f"Could not read the mailbox: {str(e)[:300]}")
    if r != "off":
        cmail._note_run(repo.engine, r)                                          # noqa: SLF001
    return {"result": "Replies are switched off." if r == "off" else r}


# ---------------------------------------------------------------- training and development
TRAINING_UPLOAD_MB = int(os.getenv("TRAINING_UPLOAD_MB", "200"))


def _training_for(conn, tid: str, me: dict, need_manage: bool):
    t = repo.get_records(conn, "trainings", [tid]).get(tid)
    if not t:
        raise HTTPException(404, "That training is not saved yet.")
    ctx = policy.make_ctx(me, repo.employees_index(conn), repo.registered_companies(conn))
    manage = ctx.is_hr_for(t.get("companyId")) or training.is_trainer(t, me["id"])
    if need_manage and not manage:
        raise HTTPException(403, "Only HR and the trainer can do this.")
    return t, ctx, manage


@app.post("/api/training/upload")
async def training_upload(trainingId: str = Form(...), file: UploadFile = File(...), me=Depends(current_user)):
    """Training content: slides, documents, spreadsheets, PDFs, pictures, audio, video or a zip. HR and the
    training's trainers upload it; it opens for the people who attended (see _file_visible)."""
    with repo.engine.connect() as conn:
        t, _ctx, _m = _training_for(conn, trainingId, me, True)
    data = await file.read()
    if len(data) > TRAINING_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"Training content can be up to {TRAINING_UPLOAD_MB} MB a file. Share larger videos as a link.")
    mime = file.content_type or "application/octet-stream"
    if not mime.startswith(training.CONTENT_MIME):
        raise HTTPException(400, "Upload a document, presentation, spreadsheet, PDF, picture, audio, video or zip file.")
    fid = _store_file(data, file.filename, mime, t.get("companyId"), me["id"])
    return {"id": fid, "name": file.filename, "size": len(data), "mime": mime}


class ScoreBody(BaseModel):
    trainingId: str
    phase: str
    answers: dict = Field(default_factory=dict)


@app.post("/api/training/score")
def training_score(body: ScoreBody, me=Depends(current_user)):
    """Marks a participant's answers. The correct answers never leave the server for participants; the same
    marking is applied again when the answers are saved."""
    with repo.engine.connect() as conn:
        t, _ctx, manage = _training_for(conn, body.trainingId, me, False)
        if not manage and not conn.execute(text("SELECT 1 FROM training_enrolments WHERE training_id=:t AND emp_id=:e AND status IN ('requested','approved','attended')"),
                                           {"t": t["id"], "e": me["id"]}).fetchone():
            raise HTTPException(403, "You are not taking part in this training.")
    if body.phase not in ("pre", "post") or not (t.get("quiz") or {}).get(body.phase):
        raise HTTPException(400, "This training has no such questionnaire.")
    return training.score(t.get("quiz"), body.answers)


class TrainerReportBody(BaseModel):
    key: str              # emp:<id> for an internal trainer, ext:<e-mail or name> for an external one
    labels: dict = Field(default_factory=dict)


@app.post("/api/training/report-mail")
def training_report_mail(body: TrainerReportBody, me=Depends(current_user)):
    """E-mails a trainer their feedback report: ratings against the company's average and what to improve.
    Participants' names are never included."""
    with repo.engine.begin() as conn:
        emps = repo.employees_index(conn)
        ctx = policy.make_ctx(me, emps, repo.registered_companies(conn))
        st = repo.load_state(conn)
        trs = [t for t in st["trainings"] if ctx.is_hr_for(t.get("companyId"))]
        if not trs:
            raise HTTPException(403, "Only HR sends trainer reports.")
        ids = {t["id"] for t in trs}
        fb = [f for f in st["trainingFeedback"] if f.get("trainingId") in ids]
        en = [x for x in st["trainingEnrols"] if x.get("trainingId") in ids]
        r = training.report(body.key, trs, fb, en, body.labels)
        if not r["trainings"]:
            raise HTTPException(400, "This trainer has no completed trainings yet.")
        if body.key.startswith("emp:"):
            e = emps.get(body.key[4:]) or {}
            to, name = e.get("email"), f"{e.get('firstName', '')} {e.get('lastName', '')}".strip()
        else:
            tr = next((t.get("trainer") or {} for t in r["trainings"] if (t.get("trainer") or {}).get("email")), {})
            to, name = tr.get("email"), tr.get("name") or "Trainer"
        if not to:
            raise HTTPException(400, "There is no e-mail address for this trainer. Add it to the training.")
        if not mailer.configured():
            return {"sent": False, "reason": "e-mail is not set up on the server; print the report instead"}
        comments_block = ("\n\nWhat participants would like improved\n" + "\n".join(f"- {c}" for c in r["comments"][:30])) if r["comments"] else ""
        liked_block = ("\n\nWhat participants liked\n" + "\n".join(f"- {c}" for c in r["liked"][:15])) if r["liked"] else ""
        subject, body = email_templates.render(conn, next((t.get("companyId") for t in r["trainings"]), None), "training.feedback", {
            "name": name, "trainingsCount": len(r["trainings"]), "trainingsList": ", ".join(f"{t.get('title')} ({t.get('start')})" for t in r["trainings"]),
            "statsLine": f"{r['attended']} of {r['enrolled']} participants attended and {r['feedback']} gave feedback. Ratings are out of 5.",
            "ratingsBlock": "\n".join(f"- {x['label']}: {x['avg']}" + (f" (all our trainings {x['org']})" if x["org"] else "") for x in reversed(r["rows"])),
            "improveBlock": "\n".join(f"- {x['label']}: rated {x['avg']}" for x in r["improve"]), "commentsBlock": comments_block, "likedBlock": liked_block})
        try:
            mailer.send([to], subject, body)
        except Exception as e:  # noqa: BLE001
            log.warning("Mail failed: %s", e)
            return {"sent": False, "reason": "the e-mail server refused the message; print the report instead"}
        repo.audit_add(conn, "Trainer report e-mailed", f"{name} <{to}>", me["id"], module="training", ref_type="trainer", ref_id=body.key[:64])
        return {"sent": True, "to": to}


# ---------------------------------------------------------------- document templates (Word files filled from the database)
ISO_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _require_hr(me):
    if me.get("role") not in ("super", "hr"):
        raise HTTPException(403, "Only HR can work with document templates.")


@app.exception_handler(doctemplates.TemplateProblem)
async def template_problem_handler(_req, exc):
    return JSONResponse({"detail": str(exc)}, status_code=400)


@app.get("/api/doc-templates/fields")
def doc_fields(me=Depends(current_user)):
    _require_hr(me)
    return {"fields": doctemplates.catalogue()}


@app.post("/api/doc-templates/scan")
async def doc_scan(file: UploadFile = File(...), me=Depends(current_user)):
    """Keeps the uploaded .docx and returns the placeholders found in it (body, tables, headers and footers)."""
    _require_hr(me)
    if not (file.filename or "").lower().endswith(".docx"):
        raise HTTPException(400, "Upload a Word document saved as .docx.")
    data = await file.read()
    info = doctemplates.scan(data)
    fid = _store_file(data, file.filename, doctemplates.DOCX_MIME, me.get("companyId"), me["id"])
    return {"fileId": fid, "name": file.filename, "size": len(data), **info}


class DocGenBody(BaseModel):
    templateId: str
    empId: str
    date: str | None = None
    values: dict[str, Any] = {}      # answers for placeholders mapped as "ask"
    computed: dict[str, Any] = {}    # salary breakup worked out by the payroll rules in the browser


def _doc_prepare(conn, body: DocGenBody, me):
    _require_hr(me)
    tpl = repo.get_records(conn, "docTemplates", [body.templateId]).get(body.templateId)
    if not tpl:
        raise HTTPException(404, "Save the template first, then try again.")
    if not tpl.get("fileId"):
        raise HTTPException(400, "This template has no Word file yet.")
    ctx = _ctx(conn, me)
    emp = ctx.emps.get(body.empId)
    if not emp:
        raise HTTPException(404, "That employee does not exist.")
    if not ctx.is_hr_for(emp.get("companyId")):
        raise HTTPException(403, "You are not HR for this employee's company.")
    if (tpl.get("companyId") and tpl["companyId"] != emp.get("companyId")) or (not tpl.get("companyId") and not ctx.is_super):
        raise HTTPException(400, "This template belongs to another company.")
    on = body.date if body.date and ISO_DAY.match(body.date) else None
    dtype = repo.get_records(conn, "docTypes", [tpl.get("typeId")]).get(tpl.get("typeId")) or {}
    info = doctemplates.values(conn, emp["id"], me, on, body.computed, dtype)
    return tpl, dtype, info, _read_file(conn, tpl["fileId"]), on


@app.post("/api/doc-templates/preview")
def doc_preview(body: DocGenBody, me=Depends(current_user)):
    """The filled document to check, marked DRAFT. Nothing is numbered or saved."""
    with repo.engine.connect() as conn:
        tpl, dtype, info, data, _on = _doc_prepare(conn, body, me)
    ctx, empty = doctemplates.build_context(tpl, info["values"], info["emp"], body.values)
    out = doctemplates.render(data, ctx)
    name = doctemplates.safe_filename("DRAFT", tpl.get("name"), info["values"]["employee_name"])
    from urllib.parse import quote
    ascii_name = name.encode("ascii", "ignore").decode() or "document.docx"
    return RawResponse(out, media_type=doctemplates.DOCX_MIME, headers={
        "content-disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}",
        "x-empty-placeholders": ",".join(empty)[:2000], "access-control-expose-headers": "x-empty-placeholders"})


@app.post("/api/doc-templates/generate")
def doc_generate(body: DocGenBody, me=Depends(current_user)):
    """Fills the template, takes the next letter number for its document type and keeps the file.
    The browser then adds it to the employee's Letters and service documents."""
    with repo.engine.begin() as conn:
        tpl, dtype, info, data, on = _doc_prepare(conn, body, me)
        letter_no = doctemplates.next_letter_no(conn, dtype, info["company"], on or time.strftime("%Y-%m-%d"))
        info["values"]["letter_no"] = letter_no
        ctx, empty = doctemplates.build_context(tpl, info["values"], info["emp"], body.values)
        out = doctemplates.render(data, ctx)
        repo.audit_add(conn, "Document generated", f"{tpl.get('name')}: {info['values']['employee_name']}" + (f" ({letter_no})" if letter_no else ""),
                       me["id"], module="org", ref_type="employee", ref_id=info["emp"]["id"])
    name = doctemplates.safe_filename(tpl.get("name"), info["values"]["employee_name"], letter_no.replace("/", "-") if letter_no else "")
    fid = _store_file(out, name, doctemplates.DOCX_MIME, info["emp"].get("companyId"), me["id"])
    return {"fileId": fid, "name": name, "letterNo": letter_no, "empty": empty, "type": dtype.get("name") or tpl.get("name")}


@app.get("/api/health")
def health():
    with repo.engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"ok": True}


# ---------------------------------------------------------------- admin: e-mail templates
EMAIL_TEMPLATE_SAMPLES = {
    "access.invite": {"name": "Asha Rao", "who": "Priya Shah", "company": "Acme Pvt Ltd", "url": "https://example.com/#/welcome?t=sample", "inviteDays": 7},
    "candidate.link": {"name": "Rohit Verma", "company": "Acme Pvt Ltd", "jobLabel": "Sales Executive", "what": " for the position of Sales Executive",
                        "skillsNote": " and your level in the skills the job needs", "url": "https://example.com/#/apply?t=sample", "linkDays": 14},
    "reimb.paid": {"firstName": "Asha", "how": "with your salary for July 2026", "total": "4,250", "runNo": "RR/2627/0012", "companyName": "Acme Pvt Ltd",
                   "claims": [{"no": "EC-0101", "title": "Client visit, Pune", "amount": "2,500"}, {"no": "EC-0104", "title": "Internet reimbursement", "amount": "1,750"}]},
    "statutory.submitted": {"name": "Asha Rao", "no": "SR-0021", "changesLines": "- PAN: ABCDE1234F -> ABCDE5678F", "docCount": 1,
                             "noteLine": "\nNote: Name change after marriage", "link": "https://example.com/#/request/sample"},
    "statutory.decided": {"firstName": "Asha", "outcome": "approved", "no": "SR-0021", "changeLabels": "PAN", "noteBlock": "", "link": "https://example.com/#/request/sample"},
    "comp.launched": {"cycleName": "FY26-27 revision", "deadlineBlock": " by 2026-12-15", "effective": "2027-01-01", "link": "https://example.com/#/compplan?c=sample"},
    "comp.submitted": {"who": "Priya Shah", "cycleName": "FY26-27 revision", "link": "https://example.com/#/compplan?c=sample"},
    "comp.decided": {"who": "Priya Shah", "outcome": "approved", "outcomeVerb": "approved", "deciderName": "Rahul Menon", "cycleName": "FY26-27 revision",
                      "noteBlock": "", "link": "https://example.com/#/compplan?c=sample"},
    "comp.comment": {"who": "Priya Shah", "writerName": "Rahul Menon", "commentText": "Please revisit the increase for the Sales team.", "link": "https://example.com/#/compplan?c=sample"},
    "training.feedback": {"name": "Kiran Patel", "trainingsCount": 2, "trainingsList": "Effective Feedback (2026-09-10), Time Management (2026-10-02)",
                           "statsLine": "24 of 28 participants attended and 20 gave feedback. Ratings are out of 5.",
                           "ratingsBlock": "- Content: 4.3\n- Delivery: 4.6", "improveBlock": "- Pace: rated 3.2", "commentsBlock": "", "likedBlock": ""},
    "report.scheduled": {"name": "there", "reportName": "Monthly attrition", "when": "01 Jan 2027 08:00", "rowCount": 12},
    "recruit.shortlist": {"firstName": "Rahul", "sender": "Priya Shah", "job": "Sales Executive", "reqNo": "REQ-0012", "count": 2,
                          "candidatesLines": "- Rohit Verma: 5 years, Sales Officer at Acme, expects 6,00,000\n- Meera Iyer: 3 years, Executive at Zen, expects 5,20,000",
                          "noteBlock": "Note: Both meet every primary skill.\n", "link": "https://example.com/#/slapprove?req=sample"},
    "recruit.selection": {"firstName": "Rahul", "sender": "Priya Shah", "job": "Sales Executive", "reqNo": "REQ-0012",
                          "candidatesLines": "- Rohit Verma: select (rank 1)\n- Meera Iyer: hold", "link": "https://example.com/#/finalsel/sample"},
    "candidate.message": {"firstName": "Rohit", "subject": "Documents for joining", "text": "Please bring your relieving letter on the joining day.", "filesLine": "",
                          "replyLine": "Reply to this e-mail, or sign in to your candidate portal to reply.", "link": "https://example.com/", "sender": "Priya Shah", "company": "Aequm India Pvt Ltd"},
    "candidate.toHr": {"firstName": "Priya", "candidate": "Rohit Verma", "job": "Sales Executive", "subject": "Joining date", "via": " in the candidate portal",
                       "text": "Could I join on the 15th instead?", "filesLine": "", "replyLine": "Reply to this e-mail to answer the candidate, or answer in PeopleDesk.", "link": "https://example.com/#/app/sample"},
    "candidate.notice.interview": {"headline": "Interview", "intro": "Your interview for Sales Executive is arranged.", "job": "Sales Executive", "round": "First round",
                                   "when": "Thu 19-11-2026 at 11:00", "duration": 45, "where": "Video call: https://meet.example.com/abc", "panelLine": "With Rahul Menon and Kiran Patel.",
                                   "outro": "If the time does not suit you, reply to this message."},
    "candidate.notice.offer": {"job": "Sales Executive", "roundWord": "", "letterNo": "OL/AEQ/2026-27/0002", "expiryLine": " Please reply by 19-11-2026."},
    "recruit.referral": {"firstName": "Anil", "sender": "Rahul Menon", "candidate": "Rohit Verma", "job": "Sales Executive", "round": "Second round",
                         "questionBlock": "\n\nQuestion: Is his key-account experience enough for the North region?", "link": "https://example.com/#/app/sample"},
}


class MailTemplateTestBody(BaseModel):
    mailKey: str


@app.get("/api/email-templates/catalogue")
def email_template_catalogue(me=Depends(current_user)):
    _require_hr(me)
    return {"templates": email_templates.catalogue()}


@app.post("/api/email-templates/test", dependencies=[Depends(require_csrf)])
def email_template_test(body: MailTemplateTestBody, me=Depends(current_user)):
    _require_hr(me)
    if body.mailKey not in email_templates.DEFAULTS:
        raise HTTPException(404, "Unknown e-mail key.")
    if not mailer.configured():
        raise HTTPException(400, "E-mail is not set up on the server.")
    to = me.get("email")
    if not to:
        raise HTTPException(400, "You have no e-mail address to send the test to.")
    with repo.engine.connect() as conn:
        subject, body_text = email_templates.render(conn, me.get("companyId"), body.mailKey, EMAIL_TEMPLATE_SAMPLES.get(body.mailKey, {}))
    try:
        mailer.send([to], f"[Test] {subject}", body_text)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"The e-mail server refused the message: {e}") from None
    return {"sent": True, "to": to}


# ---------------------------------------------------------------- admin: reporting
class ReportRunBody(BaseModel):
    reportDefId: str | None = None
    baseCollection: str | None = None
    filters: list[dict] = []
    columns: list[str] = []


def _report_def_from(conn, body: ReportRunBody, me) -> dict:
    if body.reportDefId:
        rd = repo.get_records(conn, "reportDefs", [body.reportDefId]).get(body.reportDefId)
        if not rd:
            raise HTTPException(404, "That report is not saved yet.")
        return rd
    if not body.baseCollection:
        raise HTTPException(400, "Choose what to report on.")
    return {"baseCollection": body.baseCollection, "filters": body.filters, "columns": body.columns}


@app.get("/api/reports/fields")
def report_fields(me=Depends(current_user)):
    _require_hr(me)
    return {"collections": reports.catalogue()}


@app.post("/api/reports/run")
def report_run(body: ReportRunBody, me=Depends(current_user)):
    _require_hr(me)
    with repo.engine.connect() as conn:
        ctx = _ctx(conn, me)
        rd = _report_def_from(conn, body, me)
        try:
            rows = reports.run(conn, rd, ctx)
        except ValueError:
            raise HTTPException(400, "That cannot be reported on.")
    cols = reports.columns_for(rd)
    return {"rows": rows[:5000], "total": len(rows), "columns": cols}


@app.post("/api/reports/export")
def report_export(body: ReportRunBody, me=Depends(current_user)):
    _require_hr(me)
    with repo.engine.connect() as conn:
        ctx = _ctx(conn, me)
        rd = _report_def_from(conn, body, me)
        try:
            rows = reports.run(conn, rd, ctx)
        except ValueError:
            raise HTTPException(400, "That cannot be reported on.")
    cols = reports.columns_for(rd)
    data = reports.to_excel(rows, cols)
    name = f"{(rd.get('name') or rd.get('baseCollection') or 'report').replace(' ', '_')}.xlsx"
    return RawResponse(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"content-disposition": f'attachment; filename="{name}"'})


# ---------------------------------------------------------------- the built React app (production)
if os.path.isdir(FRONTEND_DIST):
    app.mount("/assets", StaticFiles(directory=os.path.join(FRONTEND_DIST, "assets")), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str, request: Request):
        root = os.path.realpath(FRONTEND_DIST)
        f = os.path.realpath(os.path.join(root, path))
        if path and not path.startswith("api/") and f.startswith(root + os.sep) and os.path.isfile(f):
            return FileResponse(f)
        if path.startswith("api/"):
            raise HTTPException(404)
        return FileResponse(os.path.join(FRONTEND_DIST, "index.html"))
