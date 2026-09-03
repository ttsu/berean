-- Structure. Run as berean_owner, which owns every object asserted here.
--
-- These are assertions about the shape of the schema rather than about
-- behaviour; the two role files beside this one exercise the behaviour, because
-- a grant is only demonstrated by a statement that is refused.

\set ON_ERROR_STOP on

-- The four schemas. `extensions` and `migration` matter as much as the two that
-- hold tables: pgvector's type is unreachable from a path that does not name the
-- first, and the migration record is rewritable by a service if it lands
-- anywhere but the second.
DO $$
DECLARE
    want text[] := ARRAY['corpus', 'trace', 'extensions', 'migration'];
    s text;
BEGIN
    FOREACH s IN ARRAY want LOOP
        ASSERT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = s),
            format('missing schema %I', s);
    END LOOP;
END $$;

-- Every relation the data model names, plus the view that restores the chunk
-- metadata contract's fourteen fields.
DO $$
DECLARE
    want text[] := ARRAY[
        'corpus.works', 'corpus.chunks', 'corpus.chunk_embeddings', 'corpus.chunk_metadata',
        'trace.responses', 'trace.traces', 'trace.candidates', 'trace.verification_results'];
    r text;
BEGIN
    FOREACH r IN ARRAY want LOOP
        ASSERT to_regclass(r) IS NOT NULL, format('missing relation %s', r);
    END LOOP;
END $$;

-- The fourteen required metadata fields, at the homes they were normalised to,
-- every one of them NOT NULL. `author` is the single exception the contract
-- allows, and it is asserted nullable rather than merely not asserted: a column
-- that quietly became NOT NULL would reject every corporate document in the
-- Phase 1 corpus.
DO $$
DECLARE
    required text[] := ARRAY[
        'corpus.works.corpus_id', 'corpus.works.work', 'corpus.works.era',
        'corpus.works.tradition', 'corpus.works.language', 'corpus.works.source_language',
        'corpus.works.text_form', 'corpus.works.edition', 'corpus.works.license',
        'corpus.works.attribution',
        'corpus.chunks.corpus_id', 'corpus.chunks.locator',
        'corpus.chunk_embeddings.embedding_model', 'corpus.chunk_embeddings.dim'];
    spec text;
    rel text;
    col text;
    is_not_null boolean;
BEGIN
    ASSERT array_length(required, 1) = 14,
        'the contract names fourteen fields, thirteen of them plus author';

    FOREACH spec IN ARRAY required LOOP
        rel := substring(spec from '^(.*)\.[^.]+$');
        col := substring(spec from '\.([^.]+)$');
        SELECT attnotnull INTO is_not_null
          FROM pg_attribute
         WHERE attrelid = rel::regclass AND attname = col AND attnum > 0 AND NOT attisdropped;
        ASSERT is_not_null IS NOT NULL, format('missing column %s', spec);
        ASSERT is_not_null, format('%s must be NOT NULL', spec);
    END LOOP;

    SELECT attnotnull INTO is_not_null
      FROM pg_attribute
     WHERE attrelid = 'corpus.works'::regclass AND attname = 'author';
    ASSERT is_not_null IS NOT NULL, 'missing column corpus.works.author';
    ASSERT NOT is_not_null, 'corpus.works.author is the one nullable metadata field';
END $$;

-- The view exposes exactly the fourteen, so the contract's read surface can be
-- checked against the contract rather than against the storage layout.
DO $$
DECLARE
    got text[];
BEGIN
    SELECT array_agg(attname::text ORDER BY attname) INTO got
      FROM pg_attribute
     WHERE attrelid = 'corpus.chunk_metadata'::regclass AND attnum > 0 AND NOT attisdropped;
    ASSERT got = ARRAY[
        'attribution', 'author', 'chunk_id', 'corpus_id', 'dim', 'edition', 'embedding_model',
        'era', 'language', 'license', 'locator', 'source_language', 'text_form', 'tradition',
        'work']::text[],
        format('corpus.chunk_metadata exposes %s', got);
END $$;

-- Closed domains, spelled as the specs spell them. A label that drifts from the
-- manifest's spelling fails at insert, which is the point of the enum, but it
-- fails one task later and looks like an ingestion bug.
DO $$
BEGIN
    ASSERT (SELECT array_agg(enumlabel::text ORDER BY enumsortorder)
              FROM pg_enum WHERE enumtypid = 'corpus.license'::regtype)
        = ARRAY['public-domain', 'cc-by', 'cc-by-sa', 'local-only', 'refused']::text[],
        'corpus.license labels';

    ASSERT (SELECT array_agg(enumlabel::text ORDER BY enumsortorder)
              FROM pg_enum WHERE enumtypid = 'corpus.text_form'::regtype)
        = ARRAY['tr', 'critical', 'majority', 'not-applicable']::text[],
        'corpus.text_form labels';

    ASSERT (SELECT array_agg(enumlabel::text ORDER BY enumsortorder)
              FROM pg_enum WHERE enumtypid = 'trace.overall_result'::regtype)
        = ARRAY['verified', 'regenerated', 'degraded']::text[],
        'trace.overall_result labels';

    ASSERT (SELECT array_agg(enumlabel::text ORDER BY enumsortorder)
              FROM pg_enum WHERE enumtypid = 'trace.confidence_level'::regtype)
        = ARRAY['high', 'medium', 'low']::text[],
        'trace.confidence_level labels';
END $$;

-- Check 1 -- "{corpus_id, locator} resolves to exactly one chunk" -- as a
-- constraint rather than as care taken in Go.
DO $$
BEGIN
    ASSERT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conrelid = 'corpus.chunks'::regclass
           AND contype = 'u'
           AND conkey = (SELECT array_agg(attnum ORDER BY attnum)
                           FROM pg_attribute
                          WHERE attrelid = 'corpus.chunks'::regclass
                            AND attname IN ('corpus_id', 'locator'))),
        'corpus.chunks needs a unique constraint on (corpus_id, locator)';
END $$;

-- The pgvector index. Without it retrieval is a sequential scan that still
-- returns the right rows, so its absence is invisible until it is expensive.
DO $$
BEGIN
    ASSERT EXISTS (
        SELECT 1
          FROM pg_index i
          JOIN pg_class c ON c.oid = i.indexrelid
          JOIN pg_am am ON am.oid = c.relam
         WHERE i.indrelid = 'corpus.chunk_embeddings'::regclass AND am.amname = 'hnsw'),
        'corpus.chunk_embeddings needs an hnsw index';
END $$;

-- Grants, from the catalogue rather than from a statement's success, so that
-- the negative half is a real assertion and not an absence of evidence. The
-- statement-level half is in the two role files.
DO $$
BEGIN
    ASSERT has_schema_privilege('catena', 'corpus', 'USAGE'), 'catena needs corpus';
    -- The whole disjointness rests on this one: without schema USAGE the trace
    -- tables are unreachable to catena regardless of any table grant a later
    -- migration gets wrong.
    ASSERT NOT has_schema_privilege('catena', 'trace', 'USAGE'), 'catena must not reach trace';
    ASSERT has_schema_privilege('gateway', 'trace', 'USAGE'), 'gateway needs trace';
    ASSERT has_schema_privilege('gateway', 'corpus', 'USAGE'), 'gateway needs to read corpus';

    -- The migration record belongs to the migrator alone.
    ASSERT NOT has_schema_privilege('catena', 'migration', 'USAGE'), 'catena must not reach migration';
    ASSERT NOT has_schema_privilege('gateway', 'migration', 'USAGE'), 'gateway must not reach migration';

    -- Nobody creates objects in public, including by accident.
    ASSERT NOT has_schema_privilege('catena', 'public', 'CREATE'), 'no CREATE on public';
    ASSERT NOT has_schema_privilege('gateway', 'public', 'CREATE'), 'no CREATE on public';
END $$;

DO $$
DECLARE
    t text;
    p text;
BEGIN
    FOREACH t IN ARRAY ARRAY['corpus.works', 'corpus.chunks', 'corpus.chunk_embeddings'] LOOP
        FOREACH p IN ARRAY ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE'] LOOP
            ASSERT has_table_privilege('catena', t, p), format('catena needs %s on %s', p, t);
        END LOOP;
        ASSERT has_table_privilege('gateway', t, 'SELECT'), format('gateway needs SELECT on %s', t);
        FOREACH p IN ARRAY ARRAY['INSERT', 'UPDATE', 'DELETE'] LOOP
            ASSERT NOT has_table_privilege('gateway', t, p),
                format('gateway is read-only on corpus, but has %s on %s', p, t);
        END LOOP;
    END LOOP;

    FOREACH t IN ARRAY ARRAY['trace.responses', 'trace.traces', 'trace.candidates',
                             'trace.verification_results'] LOOP
        FOREACH p IN ARRAY ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE'] LOOP
            ASSERT has_table_privilege('gateway', t, p), format('gateway needs %s on %s', p, t);
            ASSERT NOT has_table_privilege('catena', t, p),
                format('catena has %s on %s', p, t);
        END LOOP;
    END LOOP;

    ASSERT has_table_privilege('catena', 'corpus.chunk_metadata', 'SELECT'),
        'catena needs the metadata view';
    ASSERT has_table_privilege('gateway', 'corpus.chunk_metadata', 'SELECT'),
        'gateway needs the metadata view';
END $$;

-- Applied, and not left dirty by a failed run.
DO $$
DECLARE
    v bigint;
    dirty boolean;
BEGIN
    SELECT version, migration.schema_migrations.dirty INTO v, dirty FROM migration.schema_migrations;
    ASSERT v = 2, format('expected migration version 2, found %s', v);
    ASSERT NOT dirty, 'the migration state is dirty; a migration failed part-way';
END $$;

\echo 'owner assertions: OK'
