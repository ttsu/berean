-- Behaviour from the trust boundary's seat. Run as gateway, inside a transaction
-- that is rolled back. All invented content (ADR-0014).

\set ON_ERROR_STOP on

BEGIN;

-- Read-only on the corpus schema, deliberately, and not to be worked around.
DO $$
BEGIN
    PERFORM count(*) FROM corpus.chunks;
    PERFORM count(*) FROM corpus.chunk_metadata;

    BEGIN
        INSERT INTO corpus.works
            (corpus_id, work, era, tradition, language, source_language,
             text_form, edition, license, attribution)
        VALUES ('probe-0003-invented', 'A Probe', 'test', 'none', 'en', 'en',
                'not-applicable', 'invented', 'public-domain', 'Invented.');
        RAISE EXCEPTION 'gateway wrote to the corpus schema';
    EXCEPTION WHEN insufficient_privilege THEN NULL;
    END;
END $$;

-- A whole turn: the response, the trace for each attempt, the candidates
-- retrieval considered, and what the four checks found. One transaction,
-- because `overall_result` and `confidence` are known only once the turn ends.
INSERT INTO trace.responses
    (request_id, profile, query, answer, overall_result,
     confidence_level, confidence_reason, attempts)
VALUES
    ('00000000-0000-4000-8000-000000000001', 'probe', 'An invented question?', '{}'::jsonb,
     'regenerated', 'medium', 'One binding citation; a regeneration occurred.', 2);

INSERT INTO trace.traces
    (request_id, attempt, rewritten_query, embedding_model, dim,
     generation_model, top_k, embed_ms, search_ms, generate_ms)
VALUES
    ('00000000-0000-4000-8000-000000000001', 1, 'An invented question?',
     'probe-embedder', 1024, 'probe-generator:tag', 20, 1, 2, 3),
    ('00000000-0000-4000-8000-000000000001', 2, 'An invented question?',
     'probe-embedder', 1024, 'probe-generator:tag', 20, 1, 2, 3);

INSERT INTO trace.candidates
    (request_id, attempt, rank, corpus_id, locator, score, included, exclusion_reason)
VALUES
    ('00000000-0000-4000-8000-000000000001', 1, 1, 'probe-0000-invented', 'Probe 1.1', 0.9, true, ''),
    ('00000000-0000-4000-8000-000000000001', 1, 2, 'probe-0000-invented', 'Probe 1.2', 0.4, false,
     'below the retrieval depth actually used');

INSERT INTO trace.verification_results
    (request_id, attempt, corpus_id, locator,
     locator_resolved, quote_matched, tier_permitted, license_permitted, failure_detail)
VALUES
    ('00000000-0000-4000-8000-000000000001', 1, 'probe-0000-invented', 'Probe 9.9',
     false, false, false, false, 'no chunk at that locator in that corpus'),
    ('00000000-0000-4000-8000-000000000001', 2, 'probe-0000-invented', 'Probe 1.1',
     true, true, true, true, '');

-- A citation to a corpus that does not exist is what check 1 records. A foreign
-- key here would make the fabrication unrecordable, which is the opposite of an
-- audit log.
INSERT INTO trace.verification_results
    (request_id, attempt, corpus_id, locator,
     locator_resolved, quote_matched, tier_permitted, license_permitted, failure_detail)
VALUES
    ('00000000-0000-4000-8000-000000000001', 1, 'no-such-corpus-invented', 'Nowhere 1.1',
     false, false, false, false, 'corpus absent from the filter spec that was sent');

-- Empty exactly when every check passed, held both ways.
DO $$
BEGIN
    BEGIN
        INSERT INTO trace.verification_results
            (request_id, attempt, corpus_id, locator,
             locator_resolved, quote_matched, tier_permitted, license_permitted, failure_detail)
        VALUES ('00000000-0000-4000-8000-000000000001', 1, 'probe-0000-invented', 'Probe 2.1',
                false, true, true, true, '');
        RAISE EXCEPTION 'a failed check was recorded with no detail';
    EXCEPTION WHEN check_violation THEN NULL;
    END;

    BEGIN
        INSERT INTO trace.verification_results
            (request_id, attempt, corpus_id, locator,
             locator_resolved, quote_matched, tier_permitted, license_permitted, failure_detail)
        VALUES ('00000000-0000-4000-8000-000000000001', 1, 'probe-0000-invented', 'Probe 2.2',
                true, true, true, true, 'something failed, apparently');
        RAISE EXCEPTION 'a passing verification was recorded with a failure detail';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
END $$;

-- An excluded candidate with no reason is the retrieval regression this table
-- exists to make visible, silently unexplained.
DO $$
BEGIN
    BEGIN
        INSERT INTO trace.candidates
            (request_id, attempt, rank, corpus_id, locator, score, included, exclusion_reason)
        VALUES ('00000000-0000-4000-8000-000000000001', 1, 3,
                'probe-0000-invented', 'Probe 1.3', 0.1, false, '');
        RAISE EXCEPTION 'an excluded candidate was recorded with no reason';
    EXCEPTION WHEN check_violation THEN NULL;
    END;

    BEGIN
        INSERT INTO trace.candidates
            (request_id, attempt, rank, corpus_id, locator, score, included, exclusion_reason)
        VALUES ('00000000-0000-4000-8000-000000000001', 1, 4,
                'probe-0000-invented', 'Probe 1.4', 0.1, true, 'included, and excluded because');
        RAISE EXCEPTION 'an included candidate carried an exclusion reason';
    EXCEPTION WHEN check_violation THEN NULL;
    END;

    -- Whitespace is not a reason. Both iff-constraints btrim, because a value of
    -- three spaces satisfies `<> ''` while explaining nothing.
    BEGIN
        INSERT INTO trace.candidates
            (request_id, attempt, rank, corpus_id, locator, score, included, exclusion_reason)
        VALUES ('00000000-0000-4000-8000-000000000001', 1, 5,
                'probe-0000-invented', 'Probe 1.5', 0.1, false, '   ');
        RAISE EXCEPTION 'a blank exclusion reason was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;

    BEGIN
        INSERT INTO trace.verification_results
            (request_id, attempt, corpus_id, locator,
             locator_resolved, quote_matched, tier_permitted, license_permitted, failure_detail)
        VALUES ('00000000-0000-4000-8000-000000000001', 1, 'probe-0000-invented', 'Probe 2.3',
                false, true, true, true, '   ');
        RAISE EXCEPTION 'a blank failure detail was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
END $$;

-- The outcome enum is defined by attempt number, so the degradation rate
-- ADR-0010 needs kept clean cannot be recorded incoherently.
DO $$
BEGIN
    BEGIN
        INSERT INTO trace.responses
            (request_id, profile, query, answer, overall_result,
             confidence_level, confidence_reason, attempts)
        VALUES ('00000000-0000-4000-8000-000000000002', 'probe', 'q', '{}'::jsonb,
                'verified', 'high', 'r', 2);
        RAISE EXCEPTION 'a verified turn was recorded as taking two attempts';
    EXCEPTION WHEN check_violation THEN NULL;
    END;

    BEGIN
        INSERT INTO trace.responses
            (request_id, profile, query, answer, overall_result,
             confidence_level, confidence_reason, attempts)
        VALUES ('00000000-0000-4000-8000-000000000003', 'probe', 'q', '{}'::jsonb,
                'regenerated', 'medium', 'r', 1);
        RAISE EXCEPTION 'a regenerated turn was recorded as taking one attempt';
    EXCEPTION WHEN check_violation THEN NULL;
    END;

    -- A third attempt is the one-call-per-generation seam moving.
    BEGIN
        INSERT INTO trace.responses
            (request_id, profile, query, answer, overall_result,
             confidence_level, confidence_reason, attempts)
        VALUES ('00000000-0000-4000-8000-000000000004', 'probe', 'q', '{}'::jsonb,
                'degraded', 'low', 'r', 3);
        RAISE EXCEPTION 'a third attempt was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;

    BEGIN
        INSERT INTO trace.responses
            (request_id, profile, query, answer, overall_result,
             confidence_level, confidence_reason, attempts)
        VALUES ('00000000-0000-4000-8000-000000000005', 'probe', 'q', '{}'::jsonb,
                'partially-verified', 'low', 'r', 1);
        RAISE EXCEPTION 'an unrecognised overall_result was accepted';
    EXCEPTION WHEN invalid_text_representation THEN NULL;
    END;
END $$;

-- Deleting the turn takes its whole trace with it. A response without its
-- candidates is an eval row that silently reports recall@k of nothing.
DELETE FROM trace.responses WHERE request_id = '00000000-0000-4000-8000-000000000001';

-- Scoped to the probe turn. An unscoped count would make this file fail after a
-- single real turn had been persisted, and nothing about this assertion needs
-- the trace tables to be empty.
DO $$
DECLARE
    probe uuid := '00000000-0000-4000-8000-000000000001';
BEGIN
    ASSERT (SELECT count(*) FROM trace.traces WHERE request_id = probe) = 0,
        'traces outlived their response';
    ASSERT (SELECT count(*) FROM trace.candidates WHERE request_id = probe) = 0,
        'candidates outlived their trace';
    ASSERT (SELECT count(*) FROM trace.verification_results WHERE request_id = probe) = 0,
        'verification results outlived their trace';
END $$;

ROLLBACK;

\echo 'gateway assertions: OK'
