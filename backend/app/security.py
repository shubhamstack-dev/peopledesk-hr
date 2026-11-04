"""Passwords, session cookies and who is signed in."""
import hashlib
import hmac
import time

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import text

from . import repo
from .config import COOKIE_NAME, COOKIE_SECURE, JWT_SECRET, SESSION_HOURS

CSRF_HEADER = "x-peopledesk"


# ---------------------------------------------------------------- passwords
def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode("utf-8")[:72], bcrypt.gensalt(rounds=12)).decode()


def _legacy(salt: str, pw: str) -> str:
    """The original single-file app's scheme (400 rounds of SHA-256). Only used to accept
    passwords from a restored browser backup; they are re-hashed with bcrypt on first sign-in."""
    h = f"{salt}:{pw}"
    for _ in range(400):
        h = hashlib.sha256((salt + h).encode("utf-8")).hexdigest()
    return h


def verify_password(stored: str | None, pw: str) -> tuple[bool, bool]:
    """(matches, needs_rehash)"""
    if not stored or not pw:
        return False, False
    if stored.startswith("legacy$"):
        _, salt, h = stored.split("$", 2)
        return hmac.compare_digest(_legacy(salt, pw), h), True
    try:
        return bcrypt.checkpw(pw.encode("utf-8")[:72], stored.encode()), False
    except ValueError:
        return False, False


def get_pw_hash(conn, emp_id: str):
    return conn.execute(text("SELECT pw_hash FROM auth_credentials WHERE employee_id=:i"), {"i": emp_id}).scalar()


def set_pw_hash(conn, emp_id: str, h: str | None):
    conn.execute(text("INSERT INTO auth_credentials (employee_id, pw_hash) VALUES (:i, :h) ON DUPLICATE KEY UPDATE pw_hash=VALUES(pw_hash)"), {"i": emp_id, "h": h})


def set_google_sub(conn, emp_id: str, sub: str):
    conn.execute(text("UPDATE auth_credentials SET google_sub=NULL WHERE google_sub=:s AND employee_id<>:i"), {"s": sub, "i": emp_id})
    conn.execute(text("INSERT INTO auth_credentials (employee_id, google_sub) VALUES (:i, :s) ON DUPLICATE KEY UPDATE google_sub=VALUES(google_sub)"), {"i": emp_id, "s": sub})


# ---------------------------------------------------------------- sessions
def start_session(resp: Response, emp_id: str):
    now = int(time.time())
    token = jwt.encode({"sub": emp_id, "iat": now, "exp": now + int(SESSION_HOURS * 3600)}, JWT_SECRET, algorithm="HS256")
    resp.set_cookie(COOKIE_NAME, token, httponly=True, secure=COOKIE_SECURE, samesite="lax", max_age=int(SESSION_HOURS * 3600), path="/")


def end_session(resp: Response):
    resp.delete_cookie(COOKIE_NAME, path="/")


def require_csrf(request: Request):
    """Writes must carry a custom header. Browsers do not let another site add one to a
    request without a CORS preflight, so a forged form post from elsewhere is refused."""
    if request.method in ("POST", "PUT", "PATCH", "DELETE") and request.headers.get(CSRF_HEADER) != "1":
        raise HTTPException(403, "Missing request header")


def active_employee(emp: dict | None) -> bool:
    return bool(emp) and emp.get("status") != "exited" and not emp.get("blocked")


def current_user(request: Request, _=Depends(require_csrf)) -> dict:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(401, "Sign in to continue")
    try:
        claims = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "Your session has ended. Sign in again.")
    with repo.engine.connect() as conn:
        emp = repo.get_records(conn, "employees", [claims["sub"]]).get(claims["sub"])
    if not active_employee(emp):
        raise HTTPException(401, "This account is not active.")
    return emp
