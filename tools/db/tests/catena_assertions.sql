-- Behaviour from the writer's seat. Run as catena, inside a transaction that is
-- rolled back, so the assertions leave the database as empty as they found it.
--
-- Everything here is invented text. No corpus text enters this repository from
-- any source, and a fixture is the likeliest way it would (ADR-0014).

\set ON_ERROR_STOP on

BEGIN;

-- A 1024-wide vector without a literal 1024 numbers in the file.
CREATE TEMP VIEW probe AS
SELECT ('[' || array_to_string(array_fill(0.1::real, ARRAY[1024]), ',') || ']')::vector AS v;

-- The happy path: a work, a chunk, and its embedding, with every required field
-- populated. If this fails, no assertion below means anything.
INSERT INTO corpus.works
    (corpus_id, work, author, era, language, source_language,
     text_form, edition, license, attribution)
VALUES
    ('probe-0000-invented', 'A Probe', NULL, 'test', 'en', 'en',
     'not-applicable', 'invented', 'public-domain', 'Invented for the schema suite.');

INSERT INTO corpus.chunks (corpus_id, locator, text, content_hash, normalisation_version)
VALUES ('probe-0000-invented', 'Probe 1.1', 'The first invented probe sentence.',
        repeat('a', 64), 1);

INSERT INTO corpus.chunk_embeddings (chunk_id, embedding_model, dim, embedding)
SELECT c.id, 'probe-embedder', 1024, p.v
  FROM corpus.chunks c, probe p
 WHERE c.corpus_id = 'probe-0000-invented';

-- Scoped to the probe corpora throughout. An unscoped count would make this
-- file fail against any database that already holds an ingested corpus, and the
-- driver is written so only the reversibility leg needs an empty one.
DO $$
BEGIN
    ASSERT (SELECT count(*) FROM corpus.chunk_metadata WHERE corpus_id LIKE 'probe-%') = 1,
        'the metadata view should expose the one fully ingested probe chunk';
    ASSERT (SELECT author IS NULL FROM corpus.chunk_metadata WHERE corpus_id LIKE 'probe-%'),
        'author survives the view as NULL for a corporate document';
END $$;

-- A chunk with no embedding is not yet a chunk carrying the whole contract, and the
-- view says so rather than showing it with two nulls.
INSERT INTO corpus.chunks (corpus_id, locator, text, content_hash, normalisation_version)
VALUES ('probe-0000-invented', 'Probe 1.2', 'The second invented probe sentence.',
        repeat('b', 64), 1);

DO $$
BEGIN
    ASSERT (SELECT count(*) FROM corpus.chunk_metadata WHERE corpus_id LIKE 'probe-%') = 1,
        'an unembedded chunk must not appear in the metadata view';
END $$;

-- Check 1 is a constraint: a second chunk at the same locator in the same
-- corpus would make "resolves to exactly one chunk" unanswerable.
DO $$
BEGIN
    BEGIN
        INSERT INTO corpus.chunks (corpus_id, locator, text, content_hash, normalisation_version)
        VALUES ('probe-0000-invented', 'Probe 1.1', 'A duplicate locator.', repeat('c', 64), 1);
        RAISE EXCEPTION 'a duplicate {corpus_id, locator} was accepted';
    EXCEPTION WHEN unique_violation THEN NULL;
    END;
END $$;

-- The same locator in a different edition is not a duplicate. WCF 7.2 exists in
-- both the 1788 American revision and the 1646 original, and they differ.
INSERT INTO corpus.works
    (corpus_id, work, author, era, language, source_language,
     text_form, edition, license, attribution)
VALUES
    ('probe-0001-invented', 'A Probe', NULL, 'test', 'en', 'en',
     'not-applicable', 'invented-revision', 'public-domain', 'Invented for the schema suite.');
INSERT INTO corpus.chunks (corpus_id, locator, text, content_hash, normalisation_version)
VALUES ('probe-0001-invented', 'Probe 1.1', 'The same locator, a different edition.',
        repeat('d', 64), 1);

-- Closed domains. An unrecognised value fails at insert, which is what makes
-- check 4 a check with a domain rather than a non-empty test (ADR-0017).
DO $$
BEGIN
    BEGIN
        INSERT INTO corpus.works
            (corpus_id, work, era, language, source_language,
             text_form, edition, license, attribution)
        VALUES ('probe-0002-invented', 'A Probe', 'test', 'en', 'en',
                'not-applicable', 'invented', 'freely-available', 'Invented.');
        RAISE EXCEPTION 'an unrecognised licence was accepted';
    EXCEPTION WHEN invalid_text_representation THEN NULL;
    END;

    BEGIN
        INSERT INTO corpus.works
            (corpus_id, work, era, language, source_language,
             text_form, edition, license, attribution)
        VALUES ('probe-0002-invented', 'A Probe', 'test', 'en', 'en',
                'n/a', 'invented', 'public-domain', 'Invented.');
        RAISE EXCEPTION 'an unrecognised text_form was accepted';
    EXCEPTION WHEN invalid_text_representation THEN NULL;
    END;
END $$;

-- Licence and attribution are refused by the database, not by application code.
DO $$
BEGIN
    BEGIN
        INSERT INTO corpus.works
            (corpus_id, work, era, language, source_language,
             text_form, edition, attribution)
        VALUES ('probe-0002-invented', 'A Probe', 'test', 'en', 'en',
                'not-applicable', 'invented', 'Invented.');
        RAISE EXCEPTION 'a work with no licence was accepted';
    EXCEPTION WHEN not_null_violation THEN NULL;
    END;

    BEGIN
        INSERT INTO corpus.works
            (corpus_id, work, era, language, source_language,
             text_form, edition, license)
        VALUES ('probe-0002-invented', 'A Probe', 'test', 'en', 'en',
                'not-applicable', 'invented', 'public-domain');
        RAISE EXCEPTION 'a work with no attribution was accepted';
    EXCEPTION WHEN not_null_violation THEN NULL;
    END;

    -- An empty attribution is a missing attribution that satisfies NOT NULL.
    BEGIN
        INSERT INTO corpus.works
            (corpus_id, work, era, language, source_language,
             text_form, edition, license, attribution)
        VALUES ('probe-0002-invented', 'A Probe', 'test', 'en', 'en',
                'not-applicable', 'invented', 'public-domain', '   ');
        RAISE EXCEPTION 'a blank attribution was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
END $$;

-- A bare work ID is a bug. The check cannot prove an edition is named; it can
-- refuse the form that never names one.
DO $$
BEGIN
    BEGIN
        INSERT INTO corpus.works
            (corpus_id, work, era, language, source_language,
             text_form, edition, license, attribution)
        VALUES ('probe', 'A Probe', 'test', 'en', 'en',
                'not-applicable', 'invented', 'public-domain', 'Invented.');
        RAISE EXCEPTION 'a bare corpus_id was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
END $$;

-- `dim` is written into the trace, so it has to be the width actually stored.
DO $$
BEGIN
    BEGIN
        INSERT INTO corpus.chunk_embeddings (chunk_id, embedding_model, dim, embedding)
        SELECT c.id, 'probe-embedder-lying', 768, p.v
          FROM corpus.chunks c, probe p
         WHERE c.corpus_id = 'probe-0000-invented' AND c.locator = 'Probe 1.1';
        RAISE EXCEPTION 'a dim disagreeing with the vector was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
END $$;

-- The disjoint write scope, from catena's seat. Schema USAGE is what is missing,
-- so this fails on every trace table for the same reason and no table grant can
-- reopen it.
DO $$
BEGIN
    BEGIN
        PERFORM 1 FROM trace.responses;
        RAISE EXCEPTION 'catena reached the trace schema';
    EXCEPTION WHEN insufficient_privilege THEN NULL;
    END;

    BEGIN
        EXECUTE $q$INSERT INTO trace.responses (request_id) VALUES (gen_random_uuid())$q$;
        RAISE EXCEPTION 'catena wrote to the trace schema';
    EXCEPTION WHEN insufficient_privilege THEN NULL;
    END;
END $$;

ROLLBACK;

\echo 'catena assertions: OK'
