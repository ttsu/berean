#!/bin/bash
# Schema-level grants and default privileges for the two service roles.
#
# No tables are created here — `db/migrations/` lands all DDL, applied by the
# `migrate` service. What is asserted here is the standing policy: ALTER DEFAULT
# PRIVILEGES means a table created later by berean_owner arrives with the right
# grants rather than needing a matching GRANT statement in whichever migration
# happened to create it. The migrations re-assert table grants explicitly
# anyway, because a default privilege that silently did not apply is
# indistinguishable from one that did.
#
# This file runs once, on an empty data directory. A volume created before a
# change here does not pick it up; `make reset` is what re-runs it.
set -euo pipefail

# The heredoc stays quoted, so the database name arrives as a psql variable.
# `:"name"` expands to a quoted identifier. Hardcoding `berean` here would
# make POSTGRES_DB a knob that aborts init the first time anyone turns it.
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    -v db="$POSTGRES_DB" <<-'EOSQL'
	-- pgvector's `vector` type and its distance operators are resolved through
	-- `search_path` like every other name, so where the extension lands decides
	-- whether `ORDER BY embedding <=> $1` works at all. Its own schema rather
	-- than public: every role below names it, and nothing else becomes
	-- reachable by being in a path.
	CREATE SCHEMA extensions AUTHORIZATION berean_owner;
	CREATE EXTENSION IF NOT EXISTS vector SCHEMA extensions;
	GRANT USAGE ON SCHEMA extensions TO catena, gateway;

	-- Two schemas rather than two conventions. The disjoint write scope
	-- SHARED §5 requires is a property of the schema, so it holds for every
	-- table added later without anyone remembering to grant per table.
	CREATE SCHEMA corpus AUTHORIZATION berean_owner;  -- works, chunks, chunk_embeddings
	CREATE SCHEMA trace  AUTHORIZATION berean_owner;  -- responses, traces, candidates, verification_results

	-- The migration tool's own version table. It is created before the first
	-- migration runs, so it cannot be created by one, and it has to land
	-- somewhere: in `corpus` the default privileges below would hand catena
	-- INSERT and DELETE on the record of which migrations have been applied,
	-- and in `public` berean_owner has no CREATE. Its own schema, granted to
	-- neither service, is the only placement that is not a compromise.
	CREATE SCHEMA migration AUTHORIZATION berean_owner;

	-- Nobody creates objects in public, including by accident.
	REVOKE CREATE ON SCHEMA public FROM PUBLIC;

	-- catena: writes corpus, cannot see trace.
	GRANT USAGE ON SCHEMA corpus TO catena;
	ALTER DEFAULT PRIVILEGES FOR ROLE berean_owner IN SCHEMA corpus
	    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO catena;
	ALTER DEFAULT PRIVILEGES FOR ROLE berean_owner IN SCHEMA corpus
	    GRANT USAGE, SELECT ON SEQUENCES TO catena;

	-- gateway: writes trace, reads corpus. The read-only half is deliberate
	-- and is not to be worked around (services/gateway/AGENTS.md).
	GRANT USAGE ON SCHEMA corpus TO gateway;
	ALTER DEFAULT PRIVILEGES FOR ROLE berean_owner IN SCHEMA corpus
	    GRANT SELECT ON TABLES TO gateway;

	GRANT USAGE ON SCHEMA trace TO gateway;
	ALTER DEFAULT PRIVILEGES FOR ROLE berean_owner IN SCHEMA trace
	    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO gateway;
	ALTER DEFAULT PRIVILEGES FOR ROLE berean_owner IN SCHEMA trace
	    GRANT USAGE, SELECT ON SEQUENCES TO gateway;

	-- catena is granted nothing on trace, and is never granted USAGE on it.
	-- Without schema USAGE the tables are unreachable regardless of any table
	-- grant a later migration gets wrong.

	-- `extensions` is last in every path because `vector` is written
	-- unqualified in the DDL that declares a column and in every query that
	-- orders by distance. berean_owner needs it for the first of those, so its
	-- path is set here too rather than left at the default.
	ALTER ROLE berean_owner IN DATABASE :"db" SET search_path = corpus, trace, extensions;
	ALTER ROLE catena  IN DATABASE :"db" SET search_path = corpus, extensions;
	ALTER ROLE gateway IN DATABASE :"db" SET search_path = trace, corpus, extensions;
EOSQL
