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
"""
import logging
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

from . import doctemplates, mailer, migrate, policy, repo, training
from .collections import BY_NAME, SINGLETONS
from .config import APP_URL, CORS_ORIGINS, FRONTEND_DIST, MAX_UPLOAD_MB, UPLOAD_DIR
from .security import (active_employee, current_user, end_session, get_pw_hash, hash_password, require_csrf,
                       set_google_sub, set_pw_hash, start_session, verify_password)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("peopledesk")

app = FastAPI(title="PeopleDesk HR API", version="2.0")


@app.on_event("startup")
def _migrate():
    migrate.run(repo.engine)
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
            "allowDemo": False, "idleMin": s.get("idleMin", 30)}


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
    time.sleep(0.3)   # slows down password guessing
    bad = HTTPException(401, "E-mail or password is incorrect. Employees added from Google or Microsoft sign in with Google or Microsoft.")
    with repo.engine.begin() as conn:
        if not _public_settings(conn)["allowPassword"]:
            raise HTTPException(403, "Password sign-in is switched off. Sign in with Google.")
        emp = _find_by_email(conn, body.email)
        if not emp:
            raise bad
        ok, rehash = verify_password(get_pw_hash(conn, emp["id"]), body.password)
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
                keep.append(policy.check_upsert(conn, coll, r, olds.get(r["id"]), ctx))
            repo.upsert(conn, coll, keep, me["id"])
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
        repo.roster_set(conn, [{"empId": e["empId"], "date": e["date"], "value": str(e["value"])} for e in body.rosterSet])
        repo.roster_del(conn, [{"empId": e["empId"], "date": e["date"]} for e in body.rosterDel])
        for a in body.audit[:200]:
            repo.audit_add(conn, a.get("what", ""), a.get("detail", ""), me["id"], a.get("at"), a.get("id"), a.get("module"), a.get("refType"), a.get("refId"))
        repo.bump_rev(conn)
        return {"ok": True, "rev": repo.rev(conn)}


# ---------------------------------------------------------------- administration
def _require_super(me):
    if me.get("role") != "super":
        raise HTTPException(403, "Only the group administrator can do this.")


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
ALLOWED_MIME = ("image/", "application/pdf")


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
    mime = file.content_type or "application/octet-stream"
    if not mime.startswith(ALLOWED_MIME):
        raise HTTPException(400, "Attach a photo or a PDF.")
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
    if not allowed:
        raise HTTPException(403, "You cannot open this file.")
    root = os.path.realpath(UPLOAD_DIR)
    p = os.path.realpath(os.path.join(root, r.path))
    if not p.startswith(root + os.sep) or not os.path.isfile(p):
        raise HTTPException(404, "File not found")
    # private, no-store: on a shared computer the next person signing in must not get the file from the browser cache
    return FileResponse(p, media_type=r.mime, filename=r.name, content_disposition_type="inline", headers={"Cache-Control": "private, no-store"})


def _file_visible(conn, fid: str, me: dict) -> bool:
    """Besides the uploader and HR: the employee for letters on their own record, the people taking part in a
    claim or request, and for leave the employee, their reporting line and the workflow approvers."""
    hit = lambda table, extra="": conn.execute(text(f"SELECT emp_id, data FROM {table} WHERE JSON_SEARCH(data, 'one', :f) IS NOT NULL {extra}"), {"f": fid}).fetchall()  # noqa: E731
    if conn.execute(text("SELECT 1 FROM employees WHERE id=:i AND JSON_SEARCH(data, 'one', :f) IS NOT NULL"), {"i": me["id"], "f": fid}).fetchone():
        return True
    for table in ("expense_claims", "approval_requests"):
        if any(me["id"] in (repo.loads(d).get("participants") or []) or emp == me["id"] for emp, d in hit(table)):
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
            subject = f"Approval needed: statutory details change for {name} ({r.get('no')})"
            text_ = (f"{name} has asked to change their statutory details:\n\n" + "\n".join(lines) +
                     f"\n\n{len(r.get('documents') or [])} supporting document(s) attached in PeopleDesk." +
                     (f"\nNote: {r.get('reason')}" if r.get("reason") else "") +
                     f"\n\nReview and approve: {APP_URL}/#/request/{r['id']}\n\nThe change applies only after HR approves it.")
        elif body.event == "decided":
            if not is_hr:
                raise HTTPException(403, "Only HR can announce a decision.")
            to = [emp.get("email")]
            ok = r.get("status") == "applied"
            note = next((st.get("note") for st in reversed(r.get("steps") or []) if st.get("decision")), "")
            subject = f"Your statutory details change was {'approved' if ok else 'not approved'} ({r.get('no')})"
            text_ = (f"Dear {emp.get('firstName', '')},\n\nHR has {'approved' if ok else 'not approved'} your request to change: "
                     f"{', '.join(STAT_LABELS.get(k, k) for k in (r.get('changes') or {}))}." + (f"\n\nNote from HR: {note}" if note else "") +
                     f"\n\nSee it in PeopleDesk: {APP_URL}/#/request/{r['id']}")
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
            subject = f"Salary revision planning is open: {cycle.get('name', '')}"
            text_ = (f"Salary revision planning for {cycle.get('name', '')} is open in PeopleDesk.\n\n"
                     f"You have a budget for increases in your team. Hand part of it to the managers below you if you wish, "
                     f"propose each person's new salary and submit your plan" + (f" by {cycle['deadline']}" if cycle.get("deadline") else "") + ".\n\n"
                     f"New salaries take effect from {cycle.get('effective', '')}.\n\nOpen your plan: {link}")
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
                subject = f"Salary revision plan from {who} for your review"
                text_ = f"{who} has submitted their salary revision plan for {cycle.get('name', '')}.\n\nReview it, discuss, then approve or send it back: {link}&p={pool['id']}"
            elif body.event == "decided":
                last = next((s for s in reversed(steps) if s.get("decision")), None)
                if not last or last.get("by") != me["id"]:
                    raise HTTPException(403, "Only the person who decided can announce it.")
                ok = last.get("decision") == "approved"
                to_ids = [holder] + (next_ids if ok else [])
                subject = f"Salary revision plan of {who} {'approved' if ok else 'sent back'} by {nm(me['id'])}"
                text_ = (f"{nm(me['id'])} has {'approved' if ok else 'sent back for changes'} the salary revision plan of {who} for {cycle.get('name', '')}."
                         + (f"\n\nNote: {last.get('note')}" if last.get("note") else "") + f"\n\nOpen it: {link}&p={pool['id']}")
            elif body.event == "comment":
                c = (pool.get("comments") or [None])[-1]
                if not c or c.get("by") != me["id"]:
                    raise HTTPException(403, "Only the writer can announce a comment.")
                to_ids = [holder] + [i for s in steps for i in (s.get("approverIds") or [])] + [p.get("empId") for p in pools if p.get("id") == pool.get("parentId")]
                if nxt and nxt.get("kind") == "hr":
                    to_ids += hr_ids
                subject = f"New comment on the salary revision plan of {who}"
                text_ = f"{nm(me['id'])} wrote:\n\n{c.get('text', '')}\n\nReply in PeopleDesk: {link}&p={pool['id']}"
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
        lines = [f"Dear {name},", "", f"Thank you for running {len(r['trainings'])} training{'s' if len(r['trainings']) > 1 else ''} with us: "
                 + ", ".join(f"{t.get('title')} ({t.get('start')})" for t in r["trainings"]) + ".",
                 f"{r['attended']} of {r['enrolled']} participants attended and {r['feedback']} gave feedback. Ratings are out of 5.", "", "Ratings"]
        lines += [f"- {x['label']}: {x['avg']}" + (f" (all our trainings {x['org']})" if x["org"] else "") for x in reversed(r["rows"])]
        lines += ["", "Areas to improve"] + [f"- {x['label']}: rated {x['avg']}" for x in r["improve"]]
        if r["comments"]:
            lines += ["", "What participants would like improved"] + [f"- {c}" for c in r["comments"][:30]]
        if r["liked"]:
            lines += ["", "What participants liked"] + [f"- {c}" for c in r["liked"][:15]]
        lines += ["", "Feedback is anonymous.", "", "Human resources"]
        try:
            mailer.send([to], f"Your training feedback report ({len(r['trainings'])} training{'s' if len(r['trainings']) > 1 else ''})", "\n".join(lines))
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
