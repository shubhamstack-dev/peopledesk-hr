-- PeopleDesk version 2: manual upgrade, for databases the API cannot alter itself.
-- The API runs the same changes automatically at start-up (backend/app/migrate.py),
-- so you only need this if its database user lacks CREATE and ALTER rights.
-- Run once, as a MySQL administrator:  mysql peopledesk < 2026-10-v2.sql

CREATE TABLE IF NOT EXISTS approval_requests (id VARCHAR(64) NOT NULL PRIMARY KEY, company_id VARCHAR(64) NULL, emp_id VARCHAR(64) NULL, kind VARCHAR(255) NULL, status VARCHAR(255) NULL, data JSON NOT NULL,
  created_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3), updated_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3), updated_by VARCHAR(64) NULL,
  KEY ix_company (company_id), KEY ix_emp (emp_id), KEY ix_kind (kind), KEY ix_status (status)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE IF NOT EXISTS expense_categories (id VARCHAR(64) NOT NULL PRIMARY KEY, company_id VARCHAR(64) NULL, emp_id VARCHAR(64) NULL, name VARCHAR(255) NULL, data JSON NOT NULL,
  created_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3), updated_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3), updated_by VARCHAR(64) NULL,
  KEY ix_company (company_id), KEY ix_emp (emp_id), KEY ix_name (name)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE IF NOT EXISTS expense_claims (id VARCHAR(64) NOT NULL PRIMARY KEY, company_id VARCHAR(64) NULL, emp_id VARCHAR(64) NULL, claim_no VARCHAR(255) NULL, status VARCHAR(255) NULL, data JSON NOT NULL,
  created_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3), updated_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3), updated_by VARCHAR(64) NULL,
  KEY ix_company (company_id), KEY ix_emp (emp_id), KEY ix_claim_no (claim_no), KEY ix_status (status)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE IF NOT EXISTS performance_templates (id VARCHAR(64) NOT NULL PRIMARY KEY, company_id VARCHAR(64) NULL, emp_id VARCHAR(64) NULL, name VARCHAR(255) NULL, data JSON NOT NULL,
  created_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3), updated_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3), updated_by VARCHAR(64) NULL,
  KEY ix_company (company_id), KEY ix_emp (emp_id), KEY ix_name (name)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE IF NOT EXISTS onboardings (id VARCHAR(64) NOT NULL PRIMARY KEY, company_id VARCHAR(64) NULL, emp_id VARCHAR(64) NULL, status VARCHAR(255) NULL, doj DATE NULL, data JSON NOT NULL,
  created_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3), updated_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3), updated_by VARCHAR(64) NULL,
  KEY ix_company (company_id), KEY ix_emp (emp_id), KEY ix_status (status), KEY ix_doj (doj)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE IF NOT EXISTS onboarding_templates (id VARCHAR(64) NOT NULL PRIMARY KEY, company_id VARCHAR(64) NULL, emp_id VARCHAR(64) NULL, dept VARCHAR(255) NULL, data JSON NOT NULL,
  created_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3), updated_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3), updated_by VARCHAR(64) NULL,
  KEY ix_company (company_id), KEY ix_emp (emp_id), KEY ix_dept (dept)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE IF NOT EXISTS assets (id VARCHAR(64) NOT NULL PRIMARY KEY, company_id VARCHAR(64) NULL, emp_id VARCHAR(64) NULL, asset_type VARCHAR(255) NULL, tag VARCHAR(255) NULL, status VARCHAR(255) NULL, data JSON NOT NULL,
  created_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3), updated_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3), updated_by VARCHAR(64) NULL,
  KEY ix_company (company_id), KEY ix_emp (emp_id), KEY ix_asset_type (asset_type), KEY ix_tag (tag), KEY ix_status (status)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE IF NOT EXISTS files (id VARCHAR(64) NOT NULL PRIMARY KEY, name VARCHAR(255) NOT NULL, mime VARCHAR(128) NULL, size BIGINT NULL, path VARCHAR(512) NOT NULL,
  company_id VARCHAR(64) NULL, owner_emp VARCHAR(64) NULL, created_at BIGINT NOT NULL) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Activity log: area and the record it is about. Skip these three lines if the columns already exist.
ALTER TABLE audit_log ADD COLUMN module VARCHAR(32) NULL;
ALTER TABLE audit_log ADD COLUMN ref_type VARCHAR(32) NULL;
ALTER TABLE audit_log ADD COLUMN ref_id VARCHAR(64) NULL, ADD KEY ix_ref (ref_type, ref_id);
