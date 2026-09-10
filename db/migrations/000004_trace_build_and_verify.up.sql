-- What the Task 9 schema review found short, and nothing else.
--
-- Task 9's brief was to review this schema against Phase 2's needs before
-- writing the first row into it. Two columns were missing, and both are about
-- the same thing: a number nobody logged cannot be held constant across a
-- comparison, which is the argument `traces.generation_model` and
-- `traces.top_k` already won.
--
-- Two other gaps were found and deliberately left. The gateway's own
-- normalisation contract version is not recorded: Task 8 already states a skew
-- in `verification_results.failure_detail`, and a column would buy a GROUP BY
-- over a case that is rare and self-announcing. Token counts and cost
-- (SHARED 6) are held by Langfuse, and carrying them here is a proto change
-- plus a Catena change rather than a revision of this schema -- Phase 2 raises
-- it if the eval harness needs them outside the observability stack.

-- Which build produced this answer.
--
-- The first question asked of a verification failure, and `cmd/berean` has
-- carried a linker-set `version` for it since Task 1 while nothing recorded it.
-- Phase 2 compares a Phase 3 retriever against this phase's baseline out of one
-- table, and rows from two builds are otherwise indistinguishable in it.
--
-- No DEFAULT, deliberately. A backfilled sentinel is a fabricated build
-- identifier sitting in an audit log, and Task 9 is the first writer these
-- tables have ever had -- so there is nothing to backfill, and a migration that
-- fails here is telling the truth about a database that already holds turns
-- whose build nobody knows.
ALTER TABLE trace.responses
    ADD COLUMN gateway_version text NOT NULL
    CONSTRAINT responses_gateway_version_present CHECK (btrim(gateway_version) <> '');

-- How long verification took, per attempt.
--
-- SHARED 9 sets it at 200 ms p95 and Task 8 measured it against synthetic
-- load in its own suite, which is the right way to hold a floor and cannot
-- produce the number for turns anyone actually ran. It sits beside `embed_ms`,
-- `search_ms` and `generate_ms` because verification runs once per attempt like
-- each of them, and because a turn's wall clock is the sum of the four -- with
-- one of them missing, the trace tables cannot say where a slow turn went.
--
-- No DEFAULT, for the reason above: zero is not "unmeasured", it is a
-- measurement, and a false one.
ALTER TABLE trace.traces
    ADD COLUMN verify_ms bigint NOT NULL
    CONSTRAINT traces_verify_ms_non_negative CHECK (verify_ms >= 0);

-- No grants. The two service roles' write scope is unchanged: this migration
-- adds columns to tables `gateway` already writes and `catena` still cannot
-- reach, having no USAGE on the schema.
