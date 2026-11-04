"""Registered companies (tenants). Each has its own MySQL database; nothing is shared between them."""
import os
import re
import threading
import time
import uuid

from sqlalchemy import text

from . import migrate, repo

SLUG = re.compile(r"^[a-z][a-z0-9-]{2,29}$")
RESERVED = {"api", "admin", "www", "app", "root", "mysql", "test", "default", "system", "peopledesk", "platform"}
MAX_TENANTS = int(os.getenv("MAX_TENANTS", "100"))
SCHEMA_SQL = os.path.join(os.path.dirname(__file__), "..", "..", "database", "schema.sql")

DDL = """CREATE TABLE IF NOT EXISTS pd_tenants (
  id VARCHAR(40) NOT NULL PRIMARY KEY,
  slug VARCHAR(40) NOT NULL UNIQUE,
  name VARCHAR(200) NOT NULL,
  db_name VARCHAR(64) NOT NULL UNIQUE,
  status VARCHAR(16) NOT NULL DEFAULT 'active',
  created_at BIGINT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""

current_id = repo.contextvars.ContextVar("pd_tenant", default=None)
_cache: dict = {}
_lock = threading.Lock()


def _row(r):
    return {"id": r.id, "slug": r.slug, "name": r.name, "db": r.db_name, "status": r.status} if r else None


def ensure_registry():
    """At start-up: the registry table, and an existing single-company database is registered as the first tenant."""
    with repo.main_engine.begin() as conn:
        conn.execute(text(DDL))
        claimed = conn.execute(text("SELECT COUNT(*) FROM pd_tenants WHERE db_name=:d"), {"d": repo.MAIN_DB}).scalar()
        has_data = False
        try:
            has_data = conn.execute(text("SELECT COUNT(*) FROM companies")).scalar() > 0
        except Exception:  # noqa: BLE001 - a brand-new database
            pass
        if not claimed and has_data:
            code = conn.execute(text("SELECT JSON_UNQUOTE(JSON_EXTRACT(data, '$.code')) FROM companies ORDER BY id LIMIT 1")).scalar() or "company"
            group = conn.execute(text("SELECT data FROM app_kv WHERE k='group'")).scalar() if _has_table(conn, "app_kv") else None
            name = (repo.loads(group) or {}).get("name") if group else None
            slug = _free_slug(conn, re.sub(r"[^a-z0-9-]", "", code.lower()) or "company")
            conn.execute(text("INSERT INTO pd_tenants (id, slug, name, db_name, created_at) VALUES (:i, :s, :n, :d, :t)"),
                         {"i": uuid.uuid4().hex[:12], "s": slug, "n": name or code, "d": repo.MAIN_DB, "t": int(time.time() * 1000)})
    _cache.clear()


def _has_table(conn, t):
    return bool(conn.execute(text("SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=:t"), {"t": t}).scalar())


def _free_slug(conn, base):
    base = (base if base[:1].isalpha() else "c" + base)[:24]
    if len(base) < 3:
        base = (base + "org")[:24]
    slug, n = base, 1
    while conn.execute(text("SELECT COUNT(*) FROM pd_tenants WHERE slug=:s"), {"s": slug}).scalar() or slug in RESERVED:
        n += 1
        slug = f"{base}{n}"
    return slug


def all_tenants():
    with repo.main_engine.connect() as conn:
        return [_row(r) for r in conn.execute(text("SELECT * FROM pd_tenants WHERE status='active'")).fetchall()]


def by_slug(slug):
    slug = (slug or "").strip().lower()
    if not slug:
        return None
    t = _cache.get(("s", slug))
    if t is None:
        with repo.main_engine.connect() as conn:
            t = _row(conn.execute(text("SELECT * FROM pd_tenants WHERE slug=:s AND status='active'"), {"s": slug}).fetchone())
        if t:
            _cache[("s", slug)] = t
            _cache[("i", t["id"])] = t
    return t


def by_id(tid):
    if not tid:
        return None
    t = _cache.get(("i", tid))
    if t is None:
        with repo.main_engine.connect() as conn:
            t = _row(conn.execute(text("SELECT * FROM pd_tenants WHERE id=:i AND status='active'"), {"i": tid}).fetchone())
        if t:
            _cache[("i", tid)] = t
            _cache[("s", t["slug"])] = t
    return t


def main_tenant():
    t = _cache.get(("db", repo.MAIN_DB))
    if t is None:
        with repo.main_engine.connect() as conn:
            t = _row(conn.execute(text("SELECT * FROM pd_tenants WHERE db_name=:d AND status='active'"), {"d": repo.MAIN_DB}).fetchone())
        if t:
            _cache[("db", repo.MAIN_DB)] = t
    return t


def use(t):
    """Point this request (or thread) at a tenant's database; None blocks all company data."""
    repo.current_db.set(t["db"] if t else repo.NO_TENANT)
    current_id.set(t["id"] if t else None)


def _schema_statements():
    with open(SCHEMA_SQL, encoding="utf-8") as f:
        lines = [ln for ln in f.read().splitlines() if not ln.strip().startswith("--")]
    sql = "\n".join(lines)
    out = []
    for stmt in sql.split(";\n"):
        st = stmt.strip().rstrip(";").strip()
        if not st or re.match(r"(?is)^(CREATE\s+DATABASE|USE)\b", st):
            continue
        out.append(st)
    return out


def create(slug: str, name: str) -> dict:
    """Register a company: claim the empty first database, or create a new one with the full schema."""
    slug = (slug or "").strip().lower()
    if not SLUG.match(slug) or slug in RESERVED:
        raise ValueError("Company code for sign-in: 3 to 30 characters, starting with a letter; letters, digits and hyphens only.")
    with _lock:
        with repo.main_engine.begin() as conn:
            if conn.execute(text("SELECT COUNT(*) FROM pd_tenants WHERE slug=:s"), {"s": slug}).scalar():
                raise LookupError("That company code is taken. Choose another.")
            if conn.execute(text("SELECT COUNT(*) FROM pd_tenants")).scalar() >= MAX_TENANTS:
                raise PermissionError("No more companies can be registered on this server.")
            main_free = not conn.execute(text("SELECT COUNT(*) FROM pd_tenants WHERE db_name=:d"), {"d": repo.MAIN_DB}).scalar()
            main_empty = (not _has_table(conn, "companies")) or conn.execute(text("SELECT COUNT(*) FROM companies")).scalar() == 0
        db = repo.MAIN_DB if (main_free and main_empty) else f"{repo.MAIN_DB}_{slug.replace('-', '_')}"
        if db != repo.MAIN_DB:
            with repo.main_engine.begin() as conn:
                try:
                    conn.execute(text(f"CREATE DATABASE IF NOT EXISTS `{db}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"))
                except Exception as e:  # noqa: BLE001
                    raise RuntimeError("The database user cannot create databases for new companies. "
                                       "Give it the right once (see the deployment notes) and try again.") from e
            with repo.engine_for(db).begin() as conn:
                for st in _schema_statements():
                    conn.execute(text(st))
        migrate.run(repo.engine_for(db))
        t = {"id": uuid.uuid4().hex[:12], "slug": slug, "name": name.strip()[:200] or slug, "db": db, "status": "active"}
        with repo.main_engine.begin() as conn:
            conn.execute(text("INSERT INTO pd_tenants (id, slug, name, db_name, created_at) VALUES (:i, :s, :n, :d, :t)"),
                         {"i": t["id"], "s": slug, "n": t["name"], "d": db, "t": int(time.time() * 1000)})
        _cache.clear()
        return t


def rename(tid, name):
    with repo.main_engine.begin() as conn:
        conn.execute(text("UPDATE pd_tenants SET name=:n WHERE id=:i"), {"n": name[:200], "i": tid})
    _cache.clear()
