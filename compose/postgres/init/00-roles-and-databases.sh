#!/bin/bash
# Runs once, on an empty data directory, as the Postgres superuser.
#
# Creates the three roles and the second database. Schemas and grants are
# 01-schemas-and-grants.sh; splitting them keeps "who exists" separate from
# "what they may touch", which is the part reviewers actually read.
set -euo pipefail

# Passwords travel as psql variables, never as shell interpolation into the
# heredoc. `:'name'` expands to a correctly escaped SQL literal, so a rotated
# password containing a quote is a password rather than a syntax error, and one
# containing `$` is not silently rewritten by the shell into a role whose
# password no longer matches the .env the services authenticate with.
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    -v owner_password="$BEREAN_DB_OWNER_PASSWORD" \
    -v catena_password="$BEREAN_DB_CATENA_PASSWORD" \
    -v gateway_password="$BEREAN_DB_GATEWAY_PASSWORD" \
    -v langfuse_password="$LANGFUSE_DB_PASSWORD" <<-'EOSQL'
	-- Owns the schemas and runs migrations. Neither service authenticates as it.
	-- Two roles with disjoint write scope cannot also own their own tables: an
	-- owner can re-grant itself anything, which turns the grant boundary back
	-- into a convention. INTEGRATION-SPEC names the two service roles; this
	-- third one is what makes their disjointness enforceable.
	CREATE ROLE berean_owner LOGIN PASSWORD :'owner_password';

	-- Writes corpus tables. No access to trace tables.
	CREATE ROLE catena LOGIN PASSWORD :'catena_password';

	-- Writes session and trace tables. Read-only on corpus tables.
	CREATE ROLE gateway LOGIN PASSWORD :'gateway_password';

	-- Langfuse keeps its own database in the same instance. One Postgres
	-- (SHARED §5); separate databases so its migrations never meet ours.
	CREATE ROLE langfuse LOGIN PASSWORD :'langfuse_password';
	CREATE DATABASE langfuse OWNER langfuse;
EOSQL
