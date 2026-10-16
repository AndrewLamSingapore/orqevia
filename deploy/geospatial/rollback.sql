-- Non-destructive rollback: turn off adapter configuration and restore prior
-- application image first. Keep all schema/data/extensions for recovery.
-- This intentionally performs no DROP, DELETE or TRUNCATE.
BEGIN;
SELECT version,applied_at FROM orqevia.schema_migrations ORDER BY version;
COMMIT;
