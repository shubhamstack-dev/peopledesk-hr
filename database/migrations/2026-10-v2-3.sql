-- PeopleDesk 2.3: document types and Word templates. Manual upgrade, only for databases the API cannot alter itself
-- (the API creates these tables at start-up, see backend/app/migrate.py).
-- Run once, as a MySQL administrator:  mysql peopledesk < 2026-10-v2-3.sql

CREATE TABLE IF NOT EXISTS document_types (id VARCHAR(64) NOT NULL PRIMARY KEY, company_id VARCHAR(64) NULL, emp_id VARCHAR(64) NULL, name VARCHAR(255) NULL, prefix VARCHAR(255) NULL, data JSON NOT NULL,
  created_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3), updated_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3), updated_by VARCHAR(64) NULL,
  KEY ix_company (company_id), KEY ix_emp (emp_id), KEY ix_name (name), KEY ix_prefix (prefix)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE IF NOT EXISTS document_templates (id VARCHAR(64) NOT NULL PRIMARY KEY, company_id VARCHAR(64) NULL, emp_id VARCHAR(64) NULL, name VARCHAR(255) NULL, type_id VARCHAR(255) NULL, status VARCHAR(255) NULL, data JSON NOT NULL,
  created_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3), updated_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3), updated_by VARCHAR(64) NULL,
  KEY ix_company (company_id), KEY ix_emp (emp_id), KEY ix_name (name), KEY ix_type_id (type_id), KEY ix_status (status)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE IF NOT EXISTS doc_counters (k VARCHAR(128) NOT NULL PRIMARY KEY, n INT NOT NULL DEFAULT 0) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
