-- Check what actually exists, when the backend says authentication failed.
--
--   docker exec -i postgres-core psql -U postgres < verify.sql
--
-- This file exists because the failure mode is silent: Postgres answers a
-- missing role with the same 28P01 it uses for a wrong password, so
-- "authentication failed" does not tell you which of the two happened.

-- 1. Do the roles exist, and may they log in?
SELECT rolname, rolcanlogin
FROM pg_roles
WHERE rolname IN ('jp_reading_practice_owner', 'jp_reading_practice_app')
ORDER BY rolname;
-- Expect two rows, both with rolcanlogin = t.
-- Missing rows  -> run create_users_and_db.sql.
-- Both present  -> the password in the .env differs from the one the role
--                  was created with. Fix with:
--                  ALTER ROLE jp_reading_practice_owner WITH PASSWORD '...';

-- 2. Does the database exist, and who owns it?
SELECT datname, pg_get_userbyid(datdba) AS owner
FROM pg_database
WHERE datname = 'jp_reading_practice';
-- Expect one row owned by jp_reading_practice_owner.

-- 3. Are the default privileges in place? (Run against jp_reading_practice.)
--    An empty result here is the one failure that only shows up later: the
--    backend starts fine as the owner and then every request fails with
--    "permission denied for table".
--
--   docker exec -i postgres-core psql -U postgres -d jp_reading_practice -c "\ddp"
