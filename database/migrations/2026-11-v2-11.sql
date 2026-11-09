-- PeopleDesk 2.11: goal library, performance meetings, succession plans. Manual upgrade, only for databases the API cannot
-- alter itself (the API creates these tables at start-up, see backend/app/migrate.py).
-- Run once, as a MySQL administrator:  mysql peopledesk < 2026-11-v2-11.sql
USE peopledesk;

CREATE TABLE IF NOT EXISTS goal_library (
  id         VARCHAR(64)  NOT NULL PRIMARY KEY,
  company_id VARCHAR(64)  NULL,
  emp_id     VARCHAR(64)  NULL,
  code       VARCHAR(255) NULL,
  title      VARCHAR(255) NULL,
  kind       VARCHAR(255) NULL,
  data       JSON         NOT NULL,
  created_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  updated_by VARCHAR(64)  NULL,
  KEY ix_company (company_id),
  KEY ix_emp (emp_id),
  KEY ix_code (code),
  KEY ix_title (title),
  KEY ix_kind (kind)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS performance_meetings (
  id         VARCHAR(64)  NOT NULL PRIMARY KEY,
  company_id VARCHAR(64)  NULL,
  emp_id     VARCHAR(64)  NULL,
  kind       VARCHAR(255) NULL,
  cycle_id   VARCHAR(255) NULL,
  status     VARCHAR(255) NULL,
  day        DATE NULL,
  data       JSON         NOT NULL,
  created_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  updated_by VARCHAR(64)  NULL,
  KEY ix_company (company_id),
  KEY ix_emp (emp_id),
  KEY ix_kind (kind),
  KEY ix_cycle_id (cycle_id),
  KEY ix_status (status),
  KEY ix_day (day)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS succession_plans (
  id         VARCHAR(64)  NOT NULL PRIMARY KEY,
  company_id VARCHAR(64)  NULL,
  emp_id     VARCHAR(64)  NULL,
  cycle_id   VARCHAR(255) NULL,
  incumbent_id VARCHAR(255) NULL,
  status     VARCHAR(255) NULL,
  data       JSON         NOT NULL,
  created_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  updated_by VARCHAR(64)  NULL,
  KEY ix_company (company_id),
  KEY ix_emp (emp_id),
  KEY ix_cycle_id (cycle_id),
  KEY ix_incumbent_id (incumbent_id),
  KEY ix_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

