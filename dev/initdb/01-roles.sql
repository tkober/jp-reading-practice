-- Bootstrap SQL for a local Postgres: creates the owner/app role split this
-- app expects. Issue #4 (Docker/deploy) is expected to reuse this file for
-- the deployment stack's own bootstrap, the same way kanji-trainer's
-- dev/initdb/01-roles.sql mirrors its deploy/kanji_trainer/bootstrap/ SQL.
--
-- Run once against a database that already exists:
--   createdb jp_reading_practice
--   psql -d jp_reading_practice -f dev/initdb/01-roles.sql

CREATE ROLE jp_reading_practice_owner WITH LOGIN PASSWORD 'jp_reading_practice';
CREATE ROLE jp_reading_practice_app WITH LOGIN PASSWORD 'jp_reading_practice';

GRANT CONNECT ON DATABASE jp_reading_practice TO jp_reading_practice_app;

ALTER SCHEMA public OWNER TO jp_reading_practice_owner;
GRANT USAGE ON SCHEMA public TO jp_reading_practice_app;

-- The tables are created by the backend on startup as the owner role. The
-- app role's access to them comes from these default privileges, so the
-- backend itself never issues a GRANT.
ALTER DEFAULT PRIVILEGES
  FOR ROLE jp_reading_practice_owner
  IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE
  ON TABLES
  TO jp_reading_practice_app;

ALTER DEFAULT PRIVILEGES
  FOR ROLE jp_reading_practice_owner
  IN SCHEMA public
  GRANT USAGE, SELECT, UPDATE
  ON SEQUENCES
  TO jp_reading_practice_app;
