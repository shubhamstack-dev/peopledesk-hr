-- PeopleDesk 2.10: teams and asset kinds. Manual upgrade, only for databases the API cannot alter itself
-- (the API creates this table at start-up, see backend/app/migrate.py).
-- Run once, as a MySQL administrator:  mysql peopledesk < 2026-11-v2-10.sql
USE peopledesk;

CREATE TABLE IF NOT EXISTS asset_types (
  id         VARCHAR(64)  NOT NULL PRIMARY KEY,
  company_id VARCHAR(64)  NULL,
  emp_id     VARCHAR(64)  NULL,
  name       VARCHAR(255) NULL,
  team       VARCHAR(255) NULL,
  data       JSON         NOT NULL,
  created_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  updated_by VARCHAR(64)  NULL,
  KEY ix_company (company_id),
  KEY ix_emp (emp_id),
  KEY ix_name (name),
  KEY ix_team (team)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
