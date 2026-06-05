-- =============================================================
--  Runs ONCE on first container start (mounted into
--  /docker-entrypoint-initdb.d). Creates the two application
--  databases and a read-only role for the sandboxed SQL executor.
--  Postgres image auto-creates the DB named by POSTGRES_DB; we
--  create the rest here.
-- =============================================================

-- Spider data lives here (one schema per Spider db_id).
CREATE DATABASE spider;

-- App metadata: query logs, benchmark results, accuracy scores.
CREATE DATABASE metadata;

-- ---- Read-only role used by the SQL executor (Week 3) ----
-- The executor connects as this role so a generated query can never
-- mutate data, even if the LLM emits INSERT/UPDATE/DELETE/DROP.
-- Password is overridden at runtime via the init wrapper below if set.
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'query_executor') THEN
        CREATE ROLE query_executor LOGIN PASSWORD 'change_me_readonly';
    END IF;
END
$$;

-- Grant connect + read on the spider DB. Default privileges ensure
-- tables created LATER (when we load Spider) are also readable.
\connect spider
GRANT CONNECT ON DATABASE spider TO query_executor;
GRANT USAGE ON SCHEMA public TO query_executor;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO query_executor;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO query_executor;
