import os
import secrets
import logging
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
log = logging.getLogger("peopledesk")

# Either DATABASE_URL, or the parts (DB_HOST, DB_USER, DB_PASSWORD, DB_NAME).
# With the parts, the password may contain @ # : / and similar characters,
# because it is URL-encoded here.
if os.getenv("DB_PASSWORD") is not None and not os.getenv("DATABASE_URL"):
    DATABASE_URL = "mysql+pymysql://{}:{}@{}:{}/{}?charset=utf8mb4".format(
        quote_plus(os.getenv("DB_USER", "peopledesk")),
        quote_plus(os.getenv("DB_PASSWORD", "")),
        os.getenv("DB_HOST", "127.0.0.1"),
        os.getenv("DB_PORT", "3306"),
        os.getenv("DB_NAME", "peopledesk"),
    )
else:
    DATABASE_URL = os.getenv(
        "DATABASE_URL",
        "mysql+pymysql://peopledesk:peopledesk@127.0.0.1:3306/peopledesk?charset=utf8mb4",
    )

JWT_SECRET = os.getenv("JWT_SECRET") or ""
if not JWT_SECRET:
    JWT_SECRET = secrets.token_urlsafe(48)
    log.warning("JWT_SECRET is not set: using a random one, so everyone is signed out when the server restarts.")

SESSION_HOURS = float(os.getenv("SESSION_HOURS", "12"))
COOKIE_NAME = "pd_session"
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"   # true behind https
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
FRONTEND_DIST = os.getenv("FRONTEND_DIST", str(Path(__file__).resolve().parents[2] / "frontend" / "dist"))
MAX_BODY_MB = int(os.getenv("MAX_BODY_MB", "64"))
UPLOAD_DIR = os.getenv("UPLOAD_DIR", str(Path(__file__).resolve().parents[1] / "uploads"))
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "10"))
# E-mail for approvals (optional). Without SMTP_HOST, requests still appear in Approvals; no e-mail is sent.
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", "") or SMTP_USER
SMTP_TLS = os.getenv("SMTP_TLS", "starttls").lower()          # starttls | ssl | none
APP_URL = os.getenv("APP_URL", "").rstrip("/")                 # e.g. https://peopledeskhr.example.com, for links in e-mails
