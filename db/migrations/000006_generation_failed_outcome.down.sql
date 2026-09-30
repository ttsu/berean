-- Postgres cannot drop an enum value. The down migration is deliberately empty
-- rather than silently recreating the type: rebuilding `trace.overall_result`
-- would require dropping and recreating every column that uses it, which on a
-- table holding real traces is a data-loss operation dressed as a rollback.
-- Rolling back past 000006 leaves an unused value in the enum, which is inert.
SELECT 1;
