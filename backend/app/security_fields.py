"""
Masking-with-reveal for sensitive employee personal/statutory fields, modeled on the sibling
vendor_portal/backend_java project's SensitiveFieldService/OtpService/Masking.java -- same shape,
ported into this stack: a fixed in-code whitelist (FIELD_GROUPS, a security boundary, not
admin-editable), an admin-toggleable "is this field masked right now" switch (masked_field_config),
and a one-time code emailed to the viewer's own login address to reveal a real value
(field_unmask_otp).

This sits ON TOP of policy.py's existing access control, not instead of it. redact_state() already
decides WHO may see a field at all (self / HR for that company / a narrower finance subset); this
module only decides whether someone who is already allowed to see it gets the real value or a
masked placeholder by default. mask_employee() is called from redact_state for every employee
record that survives its existing redaction -- never for one that doesn't.

Each whitelist entry is a GROUP of one or more employee-record JSON keys that read/reveal together
(PeopleDesk's employee record has several keys that make up one human-facing "field", e.g. "bank"
is bankName+bankAcc+ifsc) -- unlike the flatter columns in the Java version's registration schema.
"""
import secrets
from datetime import datetime, timedelta

from sqlalchemy import text

from . import email_templates, mailer, repo

TAIL = "ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"

MASKED_FIELD_CONFIG_DDL = f"""CREATE TABLE IF NOT EXISTS masked_field_config (
  id INT AUTO_INCREMENT PRIMARY KEY, field VARCHAR(40) NOT NULL UNIQUE,
  masked TINYINT(1) NOT NULL DEFAULT 1, updated_at DATETIME NULL, updated_by VARCHAR(64) NULL
) {TAIL}"""

FIELD_UNMASK_OTP_DDL = f"""CREATE TABLE IF NOT EXISTS field_unmask_otp (
  id INT AUTO_INCREMENT PRIMARY KEY, user_id VARCHAR(64) NOT NULL, otp_code VARCHAR(10) NOT NULL,
  created_at DATETIME NOT NULL, otp_expires_at DATETIME NOT NULL, attempts INT NOT NULL DEFAULT 0,
  verified_at DATETIME NULL, unlock_token VARCHAR(64) NULL, unlock_expires_at DATETIME NULL,
  KEY ix_user (user_id)
) {TAIL}"""

# ───────────────────────────── whitelist ─────────────────────────────

FIELD_GROUPS: dict[str, list[str]] = {
    "pan": ["pan"], "aadhaar": ["aadhaar"], "uan": ["uan"], "pfNo": ["pfNo"], "esiNo": ["esiNo"],
    "bank": ["bankName", "bankAcc", "ifsc"],
    "personalEmail": ["personalEmail"], "phone": ["phone"],
    "address": ["address", "addrCity", "addrState", "addrPin", "addrCountry"],
    "emergency": ["emergencyName", "emergencyRelation", "emergencyPhone", "emergency"],
    "marital": ["marital"], "blood": ["blood"],
    "family": ["family"],  # array -- masked/revealed as a whole, not per member
}

FIELD_LABELS = {
    "pan": "PAN", "aadhaar": "Aadhaar", "uan": "UAN", "pfNo": "PF number", "esiNo": "ESI number",
    "bank": "Bank details", "personalEmail": "Personal e-mail", "phone": "Phone",
    "address": "Address", "emergency": "Emergency contact", "marital": "Marital status",
    "blood": "Blood group", "family": "Family details",
}

_ACCOUNT_LIKE = {"pan", "aadhaar", "uan", "pfNo", "esiNo", "bankAcc"}

# ───────────────────────────── masking ─────────────────────────────


def keep_last4(v: str) -> str:
    v = v.strip()
    if not v:
        return v
    if len(v) <= 4:
        return "*" * len(v)
    return "*" * (len(v) - 4) + v[-4:]


def mask_phone(v: str) -> str:
    v = v.strip()
    if not v:
        return v
    if len(v) <= 2:
        return "*" * len(v)
    return "*" * (len(v) - 2) + v[-2:]


def mask_email(v: str) -> str:
    v = v.strip()
    at = v.find("@")
    if at <= 0:
        return "*" * len(v) if v else v
    local, domain = v[:at], v[at:]
    masked_local = "*" if len(local) <= 1 else local[0] + "*" * (len(local) - 1)
    return masked_local + domain


def mask_generic(v: str) -> str:
    v = v.strip() if isinstance(v, str) else v
    if not v:
        return v
    return "*" * min(len(str(v)), 10)


def _mask_value(key: str, v):
    if not v and v != 0:
        return v
    if key in _ACCOUNT_LIKE:
        return keep_last4(str(v))
    if key == "phone" or key == "emergencyPhone":
        return mask_phone(str(v))
    if key == "personalEmail":
        return mask_email(str(v))
    if key == "family" and isinstance(v, list):
        return [{"masked": True} for _ in v]
    return mask_generic(v if isinstance(v, str) else str(v))


def is_masked(conn, field: str) -> bool:
    """Fail-safe default: masked if a whitelisted field somehow has no config row yet."""
    row = conn.execute(text("SELECT masked FROM masked_field_config WHERE field=:f"), {"f": field}).scalar()
    return True if row is None else bool(row)


def mask_employee(conn, e: dict) -> None:
    """Replaces each masked, present group's keys on e with their masked form, in place. Called
    from policy.redact_state for every employee record that survives its own access-control
    redaction -- this never grants visibility, only gates an already-granted one."""
    for field, keys in FIELD_GROUPS.items():
        if not is_masked(conn, field):
            continue
        for k in keys:
            if k in e and e[k] not in (None, "", [], {}):
                e[k] = _mask_value(k, e[k])


def read_group(emp: dict, field: str) -> dict:
    """The real values for one whitelist group, straight from the (unredacted) employee record."""
    keys = FIELD_GROUPS.get(field)
    if keys is None:
        raise ValueError("That value can't be revealed.")
    return {k: emp.get(k) for k in keys}


# ───────────────────────────── OTP ─────────────────────────────

CODE_LENGTH = 6
CODE_VALID_MINUTES = 5
UNLOCK_MINUTES = 10
MAX_ATTEMPTS = 5


def request_otp(conn, employee: dict) -> None:
    """Emails a fresh code to the employee's own login address."""
    to = employee.get("email")
    code = "".join(secrets.choice("0123456789") for _ in range(CODE_LENGTH))
    now = datetime.now()
    conn.execute(text(
        "INSERT INTO field_unmask_otp (user_id, otp_code, created_at, otp_expires_at) VALUES (:u, :c, :now, :exp)"),
        {"u": employee["id"], "c": code, "now": now, "exp": now + timedelta(minutes=CODE_VALID_MINUTES)})
    if to and mailer.configured():
        company_id = employee.get("companyId")
        first_name = (employee.get("firstName") or "").strip() or "there"
        subject, body = email_templates.render(conn, company_id, "security.otp",
                                                 {"name": first_name, "code": code, "expiresMin": CODE_VALID_MINUTES})
        mailer.send([to], subject, body)


def verify_code(conn, user_id: str, code: str) -> dict:
    """Checks the code against the latest pending request for this user; on success, issues an
    unlock token good for UNLOCK_MINUTES. Raises ValueError with a message safe to show the
    caller (expired / too many tries / wrong code) -- main.py turns that into a 400/409."""
    row = conn.execute(text(
        "SELECT id, otp_code, otp_expires_at, attempts FROM field_unmask_otp WHERE user_id=:u ORDER BY id DESC LIMIT 1"),
        {"u": user_id}).mappings().first()
    if not row:
        raise ValueError("Request a code first.")
    now = datetime.now()
    if row["otp_expires_at"] < now:
        raise ValueError("That code has expired. Request a new one.")
    if row["attempts"] >= MAX_ATTEMPTS:
        raise ValueError("Too many tries. Request a new code.")
    if row["otp_code"] != (code or "").strip():
        conn.execute(text("UPDATE field_unmask_otp SET attempts = attempts + 1 WHERE id=:i"), {"i": row["id"]})
        raise ValueError("That code is not right.")
    token = secrets.token_hex(32)
    expires_at = now + timedelta(minutes=UNLOCK_MINUTES)
    conn.execute(text(
        "UPDATE field_unmask_otp SET verified_at=:v, unlock_token=:t, unlock_expires_at=:e WHERE id=:i"),
        {"v": now, "t": token, "e": expires_at, "i": row["id"]})
    return {"unlockToken": token, "expiresAt": expires_at.isoformat()}


def is_unlocked(conn, user_id: str, unlock_token: str) -> bool:
    if not unlock_token:
        return False
    row = conn.execute(text(
        "SELECT unlock_expires_at FROM field_unmask_otp WHERE user_id=:u AND unlock_token=:t ORDER BY id DESC LIMIT 1"),
        {"u": user_id, "t": unlock_token}).scalar()
    return bool(row and row > datetime.now())


# ───────────────────────────── admin: list + toggle ─────────────────────────────

def admin_list_config(conn) -> list[dict]:
    rows = {r["field"]: r for r in conn.execute(text(
        "SELECT field, masked, updated_at, updated_by FROM masked_field_config")).mappings()}
    out = []
    for field in FIELD_GROUPS:
        r = rows.get(field, {"masked": True, "updated_at": None, "updated_by": None})
        out.append({"field": field, "label": FIELD_LABELS.get(field, field), "masked": bool(r["masked"]),
                    "updatedAt": r["updated_at"].isoformat() if r.get("updated_at") else None, "updatedBy": r.get("updated_by")})
    return sorted(out, key=lambda r: r["label"])


def admin_set_masked(conn, field: str, masked: bool, by: str) -> dict:
    if field not in FIELD_GROUPS:
        raise ValueError("That setting does not exist.")
    conn.execute(text(
        "INSERT INTO masked_field_config (field, masked, updated_at, updated_by) VALUES (:f, :m, :now, :by) "
        "ON DUPLICATE KEY UPDATE masked=VALUES(masked), updated_at=VALUES(updated_at), updated_by=VALUES(updated_by)"),
        {"f": field, "m": masked, "now": datetime.now(), "by": by})
    return {"field": field, "masked": masked}


def seed_config(conn) -> None:
    """One row per whitelist field, masked by default -- so the admin screen always lists all of
    them from first boot, with no separate seed migration to maintain."""
    for field in FIELD_GROUPS:
        conn.execute(text("INSERT IGNORE INTO masked_field_config (field, masked) VALUES (:f, 1)"), {"f": field})
