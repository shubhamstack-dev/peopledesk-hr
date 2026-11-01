-- PeopleDesk 2.4: compensation planning. Manual upgrade, only for databases the API cannot alter itself
-- (the API creates these tables at start-up, see backend/app/migrate.py). Statutory registers need no new tables.
-- Run once, as a MySQL administrator:  mysql peopledesk < 2026-11-v2-4.sql

CREATE TABLE IF NOT EXISTS comp_cycles (
  id         VARCHAR(64)  NOT NULL PRIMARY KEY,
  company_id VARCHAR(64)  NULL,
  emp_id     VARCHAR(64)  NULL,
  name       VARCHAR(255) NULL,
  status     VARCHAR(255) NULL,
  effective  DATE NULL,
  data       JSON         NOT NULL,
  created_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  updated_by VARCHAR(64)  NULL,
  KEY ix_company (company_id),
  KEY ix_emp (emp_id),
  KEY ix_name (name),
  KEY ix_status (status),
  KEY ix_effective (effective)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS comp_budgets (
  id         VARCHAR(64)  NOT NULL PRIMARY KEY,
  company_id VARCHAR(64)  NULL,
  emp_id     VARCHAR(64)  NULL,
  cycle_id   VARCHAR(255) NULL,
  parent_id  VARCHAR(255) NULL,
  status     VARCHAR(255) NULL,
  data       JSON         NOT NULL,
  created_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  updated_by VARCHAR(64)  NULL,
  KEY ix_company (company_id),
  KEY ix_emp (emp_id),
  KEY ix_cycle_id (cycle_id),
  KEY ix_parent_id (parent_id),
  KEY ix_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS comp_recommendations (
  id         VARCHAR(64)  NOT NULL PRIMARY KEY,
  company_id VARCHAR(64)  NULL,
  emp_id     VARCHAR(64)  NULL,
  cycle_id   VARCHAR(255) NULL,
  status     VARCHAR(255) NULL,
  data       JSON         NOT NULL,
  created_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  updated_by VARCHAR(64)  NULL,
  KEY ix_company (company_id),
  KEY ix_emp (emp_id),
  KEY ix_cycle_id (cycle_id),
  KEY ix_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
