-- PeopleDesk 2.9: contractor portal. Manual upgrade, only for databases the API cannot alter itself
-- (the API creates this table at start-up, see backend/app/migrate.py).
-- Run once, as a MySQL administrator:  mysql peopledesk < 2026-11-v2-9.sql
USE peopledesk;

-- Passwords of contractors' portal users (the users themselves are on the contractor record)
CREATE TABLE IF NOT EXISTS contractor_credentials (
  user_id       VARCHAR(64)  NOT NULL PRIMARY KEY,
  contractor_id VARCHAR(64)  NOT NULL,
  pw_hash       VARCHAR(100) NULL,
  last_login    BIGINT       NULL,
  updated_at    TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  KEY ix_contractor (contractor_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
