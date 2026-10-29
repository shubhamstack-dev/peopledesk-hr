"""Sends e-mail through the SMTP server in the settings (Microsoft 365, Google Workspace or any other)."""
import logging
import smtplib
import ssl
from email.message import EmailMessage

from .config import SMTP_FROM, SMTP_HOST, SMTP_PASSWORD, SMTP_PORT, SMTP_TLS, SMTP_USER

log = logging.getLogger("peopledesk")


def configured() -> bool:
    return bool(SMTP_HOST and SMTP_FROM)


def send(to: list[str], subject: str, text: str, html: str | None = None) -> None:
    to = [t for t in dict.fromkeys(to) if t]
    if not to:
        raise ValueError("nobody to send to")
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = SMTP_FROM, ", ".join(to), subject
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    ctx = ssl.create_default_context()
    if SMTP_TLS == "ssl":
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ctx, timeout=20) as s:
            if SMTP_USER:
                s.login(SMTP_USER, SMTP_PASSWORD)
            s.send_message(msg)
    else:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as s:
            if SMTP_TLS == "starttls":
                s.starttls(context=ctx)
            if SMTP_USER:
                s.login(SMTP_USER, SMTP_PASSWORD)
            s.send_message(msg)
    log.info("Mail sent to %s: %s", to, subject)
