#!/bin/bash
# Schema-level grants and default privileges for the two service roles.
#
# No tables exist yet — Task 3 lands all DDL. What is asserted here is the
# standing policy: ALTER DEFAULT PRIVILEGES means a table created later by
# berean_owner arrives with the right grants rather than needing a matching
# GRANT statement in whichever migration happened to create it. Task 3
# re-asserts table grants explicitly anyway, because a default privilege that
# silently did not apply is indistinguishable from one that did.
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-'EOSQL'
	CREATE EXTENSION IF NOT EXISTS vector;

	-- Two schemas rather than two conventions. The disjoint write scope
	-- SHARED §5 requires is a property of the schema, so it holds for every
	-- table added later without anyone remembering to grant per table.
	CREATE SCHEMA corpus AUTHORIZATION berean_owner;  -- works, chunks, chunk_embeddings
	CREATE SCHEMA trace  AUTHORIZATION berean_owner;  -- responses, traces, verification_results

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

	ALTER ROLE catena  IN DATABASE berean SET search_path = corpus;
	ALTER ROLE gateway IN DATABASE berean SET search_path = trace, corpus;
EOSQL
