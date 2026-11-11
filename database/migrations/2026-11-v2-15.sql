-- PeopleDesk 2.15: reimbursement runs. Manual upgrade, only for databases the API cannot alter itself (the API creates
-- this table at start-up, see backend/app/migrate.py). Run once, as a MySQL administrator:  mysql peopledesk < 2026-11-v2-15.sql
USE peopledesk;

CREATE TABLE IF NOT EXISTS reimbursement_runs (
  id         VARCHAR(64)  NOT NULL PRIMARY KEY,
  company_id VARCHAR(64)  NULL,
  emp_id     VARCHAR(64)  NULL,
  run_no     VARCHAR(255) NULL,
  status     VARCHAR(255) NULL,
  run_date   DATE NULL,
  data       JSON         NOT NULL,
  created_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  updated_by VARCHAR(64)  NULL,
  KEY ix_company (company_id),
  KEY ix_emp (emp_id),
  KEY ix_run_no (run_no),
  KEY ix_status (status),
  KEY ix_run_date (run_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
