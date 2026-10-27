"""Reading and writing the app state in MySQL."""
import json
import time
import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

from .collections import BY_NAME, COLLS, SINGLETONS, column_values
from .config import DATABASE_URL

engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=1800, future=True)

AUDIT_KEEP = 1000


def dumps(v) -> str:
    # The browser sends Infinity as null (JSON has no Infinity); the app reads null as "no upper limit".
    return json.dumps(v, ensure_ascii=False, separators=(",", ":"), default=str, allow_nan=False)


def loads(s):
    if s is None:
        return None
    if isinstance(s, (dict, list)):
        return s
    return json.loads(s)


# ---------------------------------------------------------------- reading
def blank_state() -> dict:
    st = {c.name: [] for c in COLLS}
    st.update({"group": {"name": ""}, "settings": {}, "stat": None, "seq": {}, "roster": {}, "audit": [], "v": 1})
    return st


def is_empty(conn: Connection) -> bool:
    return conn.execute(text("SELECT COUNT(*) FROM companies")).scalar() == 0


def load_state(conn: Connection) -> dict:
    st = blank_state()
    for c in COLLS:
        rows = conn.execute(text(f"SELECT data FROM {c.table} ORDER BY created_at, id")).scalars()
        st[c.name] = [loads(r) for r in rows]
    for k, data in conn.execute(text("SELECT k, data FROM app_kv")):
        if k in SINGLETONS:
            st[k] = loads(data)
    roster: dict = {}
    for emp_id, day, value in conn.execute(text("SELECT emp_id, day, value FROM roster")):
        roster.setdefault(emp_id, {})[day.isoformat()] = value
    st["roster"] = roster
    st["audit"] = [
        {"id": i, "at": at, "by": by, "what": what, "detail": detail}
        for i, at, by, what, detail in conn.execute(
            text("SELECT id, at, by_emp, what, detail FROM audit_log ORDER BY at DESC LIMIT :n"), {"n": AUDIT_KEEP})
    ]
    return st


def get_records(conn: Connection, coll_name: str, ids) -> dict:
    ids = [i for i in ids if i]
    if not ids:
        return {}
    c = BY_NAME[coll_name]
    out = {}
    for chunk in _chunks(ids, 500):
        q = text(f"SELECT id, data FROM {c.table} WHERE id IN :ids").bindparams(_expanding("ids"))
        for i, d in conn.execute(q, {"ids": chunk}):
            out[i] = loads(d)
    return out


def get_singleton(conn: Connection, k: str):
    v = conn.execute(text("SELECT data FROM app_kv WHERE k=:k"), {"k": k}).scalar()
    return loads(v)


def employees_index(conn: Connection) -> dict:
    """id -> employee record, for permission checks."""
    return {i: loads(d) for i, d in conn.execute(text("SELECT id, data FROM employees"))}


def lookup_company(conn: Connection, table: str, rec_id: str):
    return conn.execute(text(f"SELECT company_id FROM {table} WHERE id=:i"), {"i": rec_id}).scalar()


def lookup_field(conn: Connection, table: str, rec_id: str, col: str):
    return conn.execute(text(f"SELECT {col} FROM {table} WHERE id=:i"), {"i": rec_id}).scalar()


def rev(conn: Connection) -> int:
    return conn.execute(text("SELECT rev FROM app_meta WHERE id=1")).scalar() or 0


# ---------------------------------------------------------------- writing
def upsert(conn: Connection, coll_name: str, recs: list, by: str | None):
    if not recs:
        return
    c = BY_NAME[coll_name]
    cols = ["id", "company_id", "emp_id", *c.extra.keys(), "data", "updated_by"]
    placeholders = ", ".join(f":{x}" for x in cols)
    updates = ", ".join(f"{x}=VALUES({x})" for x in cols if x != "id")
    sql = text(f"INSERT INTO {c.table} ({', '.join(cols)}) VALUES ({placeholders}) ON DUPLICATE KEY UPDATE {updates}")
    rows = []
    for r in recs:
        row = {"id": str(r["id"]), **column_values(c, r), "data": dumps(r), "updated_by": by}
        rows.append(row)
    for chunk in _chunks(rows, 500):
        conn.execute(sql, chunk)


def delete(conn: Connection, coll_name: str, ids: list):
    if not ids:
        return
    c = BY_NAME[coll_name]
    for chunk in _chunks(ids, 500):
        conn.execute(text(f"DELETE FROM {c.table} WHERE id IN :ids").bindparams(_expanding("ids")), {"ids": chunk})


def set_singleton(conn: Connection, k: str, v):
    conn.execute(text("INSERT INTO app_kv (k, data) VALUES (:k, :d) ON DUPLICATE KEY UPDATE data=VALUES(data)"), {"k": k, "d": dumps(v)})


def roster_set(conn: Connection, entries: list):
    if entries:
        conn.execute(text("INSERT INTO roster (emp_id, day, value) VALUES (:empId, :date, :value) ON DUPLICATE KEY UPDATE value=VALUES(value)"), entries)


def roster_del(conn: Connection, entries: list):
    for e in entries:
        conn.execute(text("DELETE FROM roster WHERE emp_id=:empId AND day=:date"), e)


def audit_add(conn: Connection, what: str, detail: str = "", by: str | None = None, at: int | None = None, rid: str | None = None):
    conn.execute(
        text("INSERT IGNORE INTO audit_log (id, at, by_emp, what, detail) VALUES (:i, :at, :by, :w, :d)"),
        {"i": rid or uuid.uuid4().hex, "at": at or int(time.time() * 1000), "by": by, "w": (what or "")[:255], "d": (str(detail or ""))[:1000]},
    )


def bump_rev(conn: Connection):
    conn.execute(text("UPDATE app_meta SET rev = rev + 1 WHERE id=1"))


def wipe(conn: Connection):
    conn.execute(text("DELETE FROM auth_credentials"))
    for c in COLLS:
        conn.execute(text(f"DELETE FROM {c.table}"))
    for t in ("roster", "audit_log", "app_kv"):
        conn.execute(text(f"DELETE FROM {t}"))
    bump_rev(conn)


def import_state(conn: Connection, st: dict, by: str | None = None) -> dict:
    """Replaces everything with a whole state (first-time setup, demo data or a restore).
    Returns {employee_id: legacy password hash} found in the records, which are removed from them."""
    wipe(conn)
    secrets_found = {}
    for c in COLLS:
        recs = [r for r in (st.get(c.name) or []) if isinstance(r, dict)]
        for r in recs:
            if not r.get("id"):
                r["id"] = uuid.uuid4().hex[:12]
        if c.name == "employees":
            for r in recs:
                salt, h = r.pop("pwSalt", None), r.pop("pwHash", None)
                r.pop("googleSub", None)
                if salt and h:
                    secrets_found[r["id"]] = f"legacy${salt}${h}"
        upsert(conn, c.name, recs, by)
    for k in SINGLETONS:
        if st.get(k) is not None:
            set_singleton(conn, k, st[k])
    entries = [{"empId": e, "date": d, "value": v} for e, days in (st.get("roster") or {}).items() for d, v in (days or {}).items() if v]
    for chunk in _chunks(entries, 1000):
        roster_set(conn, chunk)
    for a in (st.get("audit") or [])[:AUDIT_KEEP]:
        audit_add(conn, a.get("what", ""), a.get("detail", ""), a.get("by"), a.get("at"), a.get("id"))
    return secrets_found


# ---------------------------------------------------------------- helpers
def _chunks(seq, n):
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def _expanding(name):
    from sqlalchemy import bindparam
    return bindparam(name, expanding=True)
