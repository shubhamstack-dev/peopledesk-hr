"""Sends e-mail through an SMTP server.

The server is set by the group administrator under Settings and data (stored in app_kv 'mail', passwords and the
client secret encrypted with a key made from JWT_SECRET), or else by the SMTP_* environment settings.
Sign-in to the server: a password (any provider), Microsoft 365 with OAuth (an Entra app with the Exchange
application permission SMTP.SendAsApp: no mailbox password, and it keeps working when Microsoft turns off password
SMTP), or none (a relay)."""
import base64
import hashlib
import json
import logging
import smtplib
import ssl
import threading
import time
from email.message import EmailMessage
from email.utils import formataddr

import requests
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import text

from . import config

log = logging.getLogger("peopledesk")
KV = "mail"
_lock = threading.Lock()
_cache = {"at": 0.0, "cfg": None}
_tokens: dict = {}

PRESETS = {
    "m365": {"host": "smtp.office365.com", "port": 587, "security": "starttls"},
    "google": {"host": "smtp.gmail.com", "port": 587, "security": "starttls"},
    "zoho": {"host": "smtppro.zoho.in", "port": 587, "security": "starttls"},
}


def _fernet() -> Fernet:
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(("peopledesk-mail:" + config.JWT_SECRET).encode()).digest()))


def encrypt(s: str) -> str:
    return _fernet().encrypt(s.encode()).decode() if s else ""


def decrypt(s: str) -> str:
    if not s:
        return ""
    try:
        return _fernet().decrypt(s.encode()).decode()
    except InvalidToken:
        log.warning("A stored mail password could not be read (JWT_SECRET changed?): enter it again in Settings.")
        return ""


def _env() -> dict:
    return {"host": config.SMTP_HOST, "port": config.SMTP_PORT, "security": config.SMTP_TLS or "starttls",
            "auth": "password" if config.SMTP_USER else "none", "user": config.SMTP_USER, "password": config.SMTP_PASSWORD,
            "fromAddr": config.SMTP_FROM, "fromName": "", "tenant": "", "clientId": "", "clientSecret": "", "source": "env"}


def stored(conn) -> dict:
    v = conn.execute(text("SELECT data FROM app_kv WHERE k=:k"), {"k": KV}).scalar()
    try:
        return json.loads(v) if v else {}
    except ValueError:
        return {}


def save(conn, d: dict):
    conn.execute(text("INSERT INTO app_kv (k, data) VALUES (:k, :d) ON DUPLICATE KEY UPDATE data=VALUES(data)"),
                 {"k": KV, "d": json.dumps(d)})
    with _lock:
        _cache["at"] = 0.0
        _tokens.clear()


def settings() -> dict:
    """The settings in force: those saved in the app, else the environment."""
    with _lock:
        if _cache["cfg"] is not None and time.time() - _cache["at"] < 30:
            return _cache["cfg"]
    cfg = _env()
    try:
        from . import repo
        with repo.engine.connect() as conn:
            d = stored(conn)
        if d.get("host"):
            cfg = {**d, "password": decrypt(d.get("password", "")), "clientSecret": decrypt(d.get("clientSecret", "")), "source": "app"}
    except Exception as e:  # noqa: BLE001 - mail must never stop the app
        log.warning("Mail settings could not be read: %s", e)
    with _lock:
        _cache.update(at=time.time(), cfg=cfg)
    return cfg


def configured() -> bool:
    s = settings()
    return bool(s.get("host") and (s.get("fromAddr") or s.get("user")))


def _m365_token(s: dict) -> str:
    key = (s.get("tenant"), s.get("clientId"))
    t = _tokens.get(key)
    if t and t[1] - 60 > time.time():
        return t[0]
    try:
        r = requests.post(f"https://login.microsoftonline.com/{s.get('tenant')}/oauth2/v2.0/token", timeout=20, data={
            "grant_type": "client_credentials", "client_id": s.get("clientId"), "client_secret": s.get("clientSecret"),
            "scope": "https://outlook.office365.com/.default"})
    except requests.RequestException as e:
        raise RuntimeError(f"Could not reach Microsoft to sign in ({type(e).__name__}). Check the server's internet access.") from e
    j = r.json() if r.content else {}
    if r.status_code != 200 or "access_token" not in j:
        raise RuntimeError("Microsoft did not give a token: " + (j.get("error_description") or j.get("error") or f"HTTP {r.status_code}").split("\r\n")[0])
    _tokens[key] = (j["access_token"], time.time() + int(j.get("expires_in", 3600)))
    return j["access_token"]


def send(to: list[str], subject: str, text_: str, html: str | None = None, cfg: dict | None = None,
         attachments: list[tuple[str, bytes, str]] | None = None, reply_to: str | None = None) -> None:
    """attachments: [(filename, data, mime type), ...]. reply_to: where replies go (2.19: the replies mailbox)."""
    s = cfg or settings()
    to = [t for t in dict.fromkeys(to) if t]
    if not to:
        raise ValueError("nobody to send to")
    if not s.get("host"):
        raise RuntimeError("E-mail is not set up.")
    sender = s.get("fromAddr") or s.get("user")
    msg = EmailMessage()
    msg["From"] = formataddr((s.get("fromName") or "", sender))
    msg["To"], msg["Subject"] = ", ".join(to), subject
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(text_)
    if html:
        msg.add_alternative(html, subtype="html")
    for name, data, mime in attachments or []:
        maintype, _, subtype = (mime or "application/octet-stream").partition("/")
        msg.add_attachment(data, maintype=maintype or "application", subtype=subtype or "octet-stream", filename=name)
    ctx = ssl.create_default_context()
    port, sec, auth = int(s.get("port") or 587), s.get("security") or "starttls", s.get("auth") or "password"
    smtp = smtplib.SMTP_SSL(s["host"], port, context=ctx, timeout=25) if sec == "ssl" else smtplib.SMTP(s["host"], port, timeout=25)
    with smtp:
        smtp.ehlo()
        if sec == "starttls":
            smtp.starttls(context=ctx)
            smtp.ehlo()
        if auth == "m365":
            token = _m365_token(s)
            user = s.get("user") or sender
            smtp.auth("XOAUTH2", lambda challenge=None: f"user={user}\x01auth=Bearer {token}\x01\x01", initial_response_ok=True)
        elif auth == "password" and s.get("user"):
            smtp.login(s["user"], s.get("password") or "")
        smtp.send_message(msg)
    log.info("Mail sent to %s: %s", to, subject)
