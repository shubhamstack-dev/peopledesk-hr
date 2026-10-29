"""
Brings an existing database up to the current schema when the API starts.

docker-compose only runs database/schema.sql on an empty volume, so a server that
already has data needs the tables and columns added since. Everything here is
additive and safe to run on every start: missing tables are created, missing
audit-log columns are added, nothing is dropped or changed.
"""
import logging

from sqlalchemy import text

from .collections import COLLS

log = logging.getLogger("peopledesk")
TAIL = "ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"
TYPES = {"str": "VARCHAR(255) NULL", "date": "DATE NULL", "month": "CHAR(7) NULL"}


def _coll_ddl(c) -> str:
    cols = ["id VARCHAR(64) NOT NULL PRIMARY KEY", "company_id VARCHAR(64) NULL", "emp_id VARCHAR(64) NULL"]
    keys = ["KEY ix_company (company_id)", "KEY ix_emp (emp_id)"]
    for col, (_k, kind) in c.extra.items():
        cols.append(f"{col} {TYPES[kind]}")
        keys.append(f"KEY ix_{col} ({col})")
    cols += ["data JSON NOT NULL", "created_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3)",
             "updated_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3)", "updated_by VARCHAR(64) NULL"]
    return f"CREATE TABLE IF NOT EXISTS {c.table} ({', '.join(cols + keys)}) {TAIL}"


FILES_DDL = f"""CREATE TABLE IF NOT EXISTS files (id VARCHAR(64) NOT NULL PRIMARY KEY, name VARCHAR(255) NOT NULL, mime VARCHAR(128) NULL,
  size BIGINT NULL, path VARCHAR(512) NOT NULL, company_id VARCHAR(64) NULL, owner_emp VARCHAR(64) NULL, created_at BIGINT NOT NULL) {TAIL}"""
# Letter numbers for generated documents: one counter per document-type prefix, company and financial year
COUNTERS_DDL = f"CREATE TABLE IF NOT EXISTS doc_counters (k VARCHAR(128) NOT NULL PRIMARY KEY, n INT NOT NULL DEFAULT 0) {TAIL}"
AUDIT_COLS = {"module": "VARCHAR(32) NULL", "ref_type": "VARCHAR(32) NULL", "ref_id": "VARCHAR(64) NULL"}


def run(engine):
    try:
        with engine.begin() as conn:
            for c in COLLS:
                conn.execute(text(_coll_ddl(c)))
            conn.execute(text(FILES_DDL))
            conn.execute(text(COUNTERS_DDL))
            have = {r[0] for r in conn.execute(text(
                "SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'audit_log'"))}
            for col, ddl in AUDIT_COLS.items():
                if col not in have:
                    conn.execute(text(f"ALTER TABLE audit_log ADD COLUMN {col} {ddl}"))
                    log.info("Added audit_log.%s", col)
            if "ref_id" not in have:
                conn.execute(text("ALTER TABLE audit_log ADD KEY ix_ref (ref_type, ref_id)"))
    except Exception as e:  # noqa: BLE001
        log.error("Database migration failed: %s. Run database/migrations/2026-10-v2.sql as a database administrator.", e)
