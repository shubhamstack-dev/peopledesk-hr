-- PeopleDesk 2.5: training and development. Manual upgrade, only for databases the API cannot alter itself
-- (the API creates these tables at start-up, see backend/app/migrate.py).
-- Run once, as a MySQL administrator:  mysql peopledesk < 2026-11-v2-5.sql

CREATE TABLE IF NOT EXISTS trainings (
  id         VARCHAR(64)  NOT NULL PRIMARY KEY,
  company_id VARCHAR(64)  NULL,
  emp_id     VARCHAR(64)  NULL,
  title      VARCHAR(255) NULL,
  status     VARCHAR(255) NULL,
  start_date DATE NULL,
  data       JSON         NOT NULL,
  created_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  updated_by VARCHAR(64)  NULL,
  KEY ix_company (company_id),
  KEY ix_emp (emp_id),
  KEY ix_title (title),
  KEY ix_status (status),
  KEY ix_start_date (start_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS training_enrolments (
  id         VARCHAR(64)  NOT NULL PRIMARY KEY,
  company_id VARCHAR(64)  NULL,
  emp_id     VARCHAR(64)  NULL,
  training_id VARCHAR(255) NULL,
  status     VARCHAR(255) NULL,
  data       JSON         NOT NULL,
  created_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  updated_by VARCHAR(64)  NULL,
  KEY ix_company (company_id),
  KEY ix_emp (emp_id),
  KEY ix_training_id (training_id),
  KEY ix_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS training_feedback (
  id         VARCHAR(64)  NOT NULL PRIMARY KEY,
  company_id VARCHAR(64)  NULL,
  emp_id     VARCHAR(64)  NULL,
  training_id VARCHAR(255) NULL,
  data       JSON         NOT NULL,
  created_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  updated_by VARCHAR(64)  NULL,
  KEY ix_company (company_id),
  KEY ix_emp (emp_id),
  KEY ix_training_id (training_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS training_needs (
  id         VARCHAR(64)  NOT NULL PRIMARY KEY,
  company_id VARCHAR(64)  NULL,
  emp_id     VARCHAR(64)  NULL,
  status     VARCHAR(255) NULL,
  data       JSON         NOT NULL,
  created_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  updated_by VARCHAR(64)  NULL,
  KEY ix_company (company_id),
  KEY ix_emp (emp_id),
  KEY ix_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
