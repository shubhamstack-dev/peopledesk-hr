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
"""
import logging
import os
import re
import time
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import text

from . import policy, repo
from .collections import BY_NAME, SINGLETONS
from .config import CORS_ORIGINS, FRONTEND_DIST
from .security import (active_employee, current_user, end_session, get_pw_hash, hash_password, require_csrf,
                       set_google_sub, set_pw_hash, start_session, verify_password)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("peopledesk")

app = FastAPI(title="PeopleDesk HR API", version="1.0")
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
    return policy.make_ctx(me, repo.employees_index(conn))


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
        return {"needsSetup": False, "group": group.get("name", ""), "companies": n_co, "settings": s, "demo": demo}


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
    bad = HTTPException(401, "E-mail or password is incorrect. Employees added from Google sign in with Google.")
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
        ctx = policy.make_ctx(me, {e["id"]: e for e in st["employees"]})
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
        for coll, ids in body.delete.items():
            if coll not in BY_NAME:
                raise HTTPException(400, f"Unknown data: {coll}")
            olds = repo.get_records(conn, coll, ids)
            for i in ids:
                if i in olds:
                    policy.check_delete(conn, coll, olds[i], ctx)
            repo.delete(conn, coll, list(olds))
        for k, v in body.singletons.items():
            if k not in SINGLETONS:
                raise HTTPException(400, f"Unknown setting: {k}")
            policy.check_singleton(k, ctx)
            if k == "settings" and not ctx.is_hr:
                continue
            repo.set_singleton(conn, k, v)
        for e in body.rosterSet + body.rosterDel:
            policy.check_roster(e.get("empId"), ctx)
        repo.roster_set(conn, [{"empId": e["empId"], "date": e["date"], "value": str(e["value"])} for e in body.rosterSet])
        repo.roster_del(conn, [{"empId": e["empId"], "date": e["date"]} for e in body.rosterDel])
        for a in body.audit[:200]:
            repo.audit_add(conn, a.get("what", ""), a.get("detail", ""), me["id"], a.get("at"), a.get("id"))
        repo.bump_rev(conn)
        return {"ok": True, "rev": repo.rev(conn)}


# ---------------------------------------------------------------- administration
def _require_super(me):
    if me.get("role") != "super":
        raise HTTPException(403, "Only the group administrator can do this.")


@app.get("/api/admin/backup")
def backup(me=Depends(current_user)):
    _require_super(me)
    with repo.engine.connect() as conn:
        st = repo.load_state(conn)
        st["_auth"] = {i: {"pw": h, "google": g} for i, h, g in conn.execute(text("SELECT employee_id, pw_hash, google_sub FROM auth_credentials"))}
        repo.audit_add(conn, "Backup downloaded", "", me["id"])
        conn.commit()
    return st


@app.post("/api/admin/restore")
def restore(body: StateBody, resp: Response, me=Depends(current_user)):
    _require_super(me)
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
    with repo.engine.begin() as conn:
        repo.wipe(conn)
    end_session(resp)
    log.warning("All data erased by %s", me.get("email"))
    return {"ok": True}


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
