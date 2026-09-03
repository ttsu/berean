#!/usr/bin/env bash
# The schema suite. Assertions about a live database, which is why this is not
# part of `make check` -- `check` runs with nothing started, and a grant is only
# demonstrated by a statement that is actually refused.
#
# Three passes, one per role, because the interesting half of the disjoint write
# scope is what each role CANNOT do, and that is unobservable from a superuser
# connection. Then a down/up cycle, because "the migration is reversible" is a
# claim about a `down` nobody has run.
#
# psql connects over the container's unix socket, which the image trusts. That
# authenticates the connection; it does not grant anything, so every assertion
# below still runs under the role's own privileges.
set -euo pipefail

cd "$(dirname "$0")/../../.."

read -r -a COMPOSE <<<"${COMPOSE:-docker compose}"
HERE=tools/db/tests

# The database name is a knob, so read it rather than hardcoding `berean` and
# failing the first time anyone turns it.
DB=$(sed -n 's/^POSTGRES_DB=//p' .env 2>/dev/null | tail -1)
DB=${DB:-berean}

if ! "${COMPOSE[@]}" ps --services --filter status=running | grep -qx postgres; then
    echo "test-schema: postgres is not running. Run 'make dev' first." >&2
    exit 1
fi

psql_as() {  # role, then psql arguments
    local role=$1
    shift
    "${COMPOSE[@]}" exec -T postgres \
        psql -v ON_ERROR_STOP=1 --quiet --no-psqlrc --username "$role" --dbname "$DB" "$@"
}

run_file() {  # role, path
    psql_as "$1" -f - <"$2"
}

value() {  # role, sql
    psql_as "$1" --tuples-only --no-align --command "$2"
}

# Compose narrates on stderr, so a bare redirect either buries the migrator's
# output or buries its error with it. Hold both, and print only on failure.
migrate_step() {
    local out
    if ! out=$("${COMPOSE[@]}" run --rm migrate "$@" 2>&1); then
        printf '%s\n' "$out" >&2
        exit 1
    fi
}

run_file berean_owner "$HERE/owner_assertions.sql"
run_file catena "$HERE/catena_assertions.sql"
run_file gateway "$HERE/gateway_assertions.sql"

# Reversibility. `down` drops tables, so this leg runs only against a database
# with nothing in it. Skipping loudly beats a test target that quietly destroys
# an afternoon of ingestion.
rows=$(value berean_owner \
    "SELECT (SELECT count(*) FROM corpus.works) + (SELECT count(*) FROM trace.responses)")
if [ "$rows" != "0" ]; then
    echo "test-schema: OK (reversibility skipped -- the database holds $rows rows; 'make reset' to include it)"
    exit 0
fi

steps=$(find db/migrations -name '*.up.sql' | wc -l | tr -d ' ')
migrate_step down "$steps"
gone=$(value berean_owner \
    "SELECT count(*) FROM (VALUES ('corpus.works'), ('corpus.chunks'), ('corpus.chunk_embeddings'),
                                  ('corpus.chunk_metadata'), ('trace.responses'), ('trace.traces'),
                                  ('trace.candidates'), ('trace.verification_results')) AS t(rel)
      WHERE to_regclass(rel) IS NOT NULL")
if [ "$gone" != "0" ]; then
    echo "test-schema: down left $gone relations behind" >&2
    exit 1
fi

migrate_step up
run_file berean_owner "$HERE/owner_assertions.sql"

echo "test-schema: OK (down and up both clean)"
