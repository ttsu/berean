-- Trace tables. The gateway writes them; catena has no USAGE on this schema and
-- therefore cannot reach them regardless of any table grant a later migration
-- gets wrong.
--
-- These are simultaneously the audit log and the Phase 2 eval dataset, which is
-- why they record the settings as well as the results, and why the candidates
-- are rows rather than a JSON array: recall@k is measured separately from
-- answer faithfulness (SHARED §7), and it is a join over this table.

CREATE TYPE trace.overall_result AS ENUM (
    -- Verified on the first attempt. An honest non-answer carrying
    -- `no_answer_reason` is VERIFIED too: the corpus being silent is a pass,
    -- and collapsing it into `degraded` makes both metrics unreadable.
    'verified',
    -- The first attempt failed and the regeneration verified (ADR-0010).
    'regenerated',
    -- The user saw "I can't source this adequately." A successful outcome of
    -- the verification system, not an error; metrics must not read this column
    -- as a failure rate.
    'degraded'
);

CREATE TYPE trace.confidence_level AS ENUM ('high', 'medium', 'low');

-- One row per turn.
CREATE TABLE trace.responses (
    -- The correlation key across the trace, the response, and the Langfuse
    -- span. A uuid rather than the proto's `string`: proto3 has no uuid type,
    -- and the column that everything else in this schema keys on is worth
    -- constraining at the one place that can.
    request_id uuid PRIMARY KEY,

    -- The resolved profile's name. Golden sets are tradition-parameterised, so
    -- Phase 2 slices on this before it slices on anything else.
    profile text NOT NULL CHECK (btrim(profile) <> ''),
    query text NOT NULL CHECK (btrim(query) <> ''),

    -- The AnswerObject as protojson. The proto is the contract, defined once
    -- and generated for both sides; a column per answer field would be exactly
    -- the hand-maintained struct SHARED §5 prohibits, one layer further out.
    answer jsonb NOT NULL,

    overall_result trace.overall_result NOT NULL,

    -- Both halves are derived by Go and overwrite whatever Python sent. A
    -- model-authored confidence is introspection wearing a structured field's
    -- clothes (ADR-0020), and it would arrive here indistinguishable from the
    -- derived one.
    confidence_level trace.confidence_level NOT NULL,
    confidence_reason text NOT NULL CHECK (btrim(confidence_reason) <> ''),

    -- One generation attempt plus at most one regeneration. A third is the seam
    -- being in the wrong place (ADR-0002, ADR-0010).
    attempts smallint NOT NULL CHECK (attempts IN (1, 2)),

    created_at timestamptz NOT NULL DEFAULT now(),

    -- The two outcomes the enum defines by attempt number, held here so the
    -- degradation rate ADR-0010 needs kept clean cannot be recorded
    -- incoherently. `degraded` is left free: whether a failure that cannot be
    -- retried degrades at one attempt or two is Task 8's to decide.
    CONSTRAINT responses_verified_is_first_attempt
        CHECK (overall_result <> 'verified' OR attempts = 1),
    CONSTRAINT responses_regenerated_is_second_attempt
        CHECK (overall_result <> 'regenerated' OR attempts = 2)
);

CREATE INDEX responses_profile_created_at_idx ON trace.responses (profile, created_at);

-- One row per generation attempt: the RetrievalTrace Python returned inside the
-- response, which Go persists.
CREATE TABLE trace.traces (
    request_id uuid NOT NULL REFERENCES trace.responses (request_id) ON DELETE CASCADE,
    attempt smallint NOT NULL CHECK (attempt IN (1, 2)),

    -- Phase 1: identical to the query. Stored anyway, so Phase 3's rewriting is
    -- measurable against a baseline that recorded what it did not do.
    rewritten_query text NOT NULL CHECK (btrim(rewritten_query) <> ''),

    embedding_model text NOT NULL CHECK (btrim(embedding_model) <> ''),
    dim integer NOT NULL CHECK (dim > 0),

    -- The pinned tag, e.g. qwen3:8b-q4_K_M (ADR-0018), and the depth actually
    -- used rather than the configured default. These are the two settings most
    -- likely to move the Phase 2 baseline silently, and a number nobody logged
    -- cannot be held constant across a comparison.
    generation_model text NOT NULL CHECK (btrim(generation_model) <> ''),
    top_k integer NOT NULL CHECK (top_k > 0),

    embed_ms bigint NOT NULL CHECK (embed_ms >= 0),
    search_ms bigint NOT NULL CHECK (search_ms >= 0),
    generate_ms bigint NOT NULL CHECK (generate_ms >= 0),

    PRIMARY KEY (request_id, attempt)
);

-- Every candidate retrieval considered, included or not.
--
-- Rows rather than a jsonb array on `traces`, because this is the table Phase 2
-- computes recall@k from and the spec asks for a trace schema designed with
-- that consumer in mind. `rank` has no counterpart in the proto: a repeated
-- field carries its order positionally and a table has no order without a
-- column, and the order is the whole of what @k means.
CREATE TABLE trace.candidates (
    request_id uuid NOT NULL,
    attempt smallint NOT NULL,
    rank integer NOT NULL CHECK (rank > 0),

    -- No foreign key to corpus.works. The gateway is read-only on the corpus
    -- schema by design, and an audit record that a corpus lifecycle event could
    -- cascade away is not an audit record.
    corpus_id text NOT NULL CHECK (btrim(corpus_id) <> ''),
    locator text NOT NULL CHECK (btrim(locator) <> ''),

    score real NOT NULL,
    included boolean NOT NULL,
    exclusion_reason text NOT NULL DEFAULT '',

    PRIMARY KEY (request_id, attempt, rank),
    FOREIGN KEY (request_id, attempt)
        REFERENCES trace.traces (request_id, attempt) ON DELETE CASCADE,

    -- The proto says the reason is empty when the candidate was included. Held
    -- both ways: an excluded candidate with no reason is the retrieval
    -- regression this table exists to make visible, silently unexplained.
    -- btrim, like every other text column here: a reason of three spaces
    -- satisfies `<> ''` while recording exactly the unexplained exclusion this
    -- constraint exists to prevent.
    CONSTRAINT candidates_reason_iff_excluded
        CHECK (included = (btrim(exclusion_reason) = ''))
);

-- Phase 1's confessional-question-retrieves-only-verses result, and Phase 2's
-- recall@k, are both a lookup by corpus.
CREATE INDEX candidates_corpus_locator_idx ON trace.candidates (corpus_id, locator);

-- One row per citation per attempt: what the four checks found.
CREATE TABLE trace.verification_results (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    request_id uuid NOT NULL,
    attempt smallint NOT NULL,

    -- Again no foreign key to corpus.works, and here it is load-bearing rather
    -- than merely prudent: a citation to a corpus that does not exist is
    -- precisely what check 1 records, and a foreign key would make the
    -- fabrication unrecordable.
    corpus_id text NOT NULL CHECK (btrim(corpus_id) <> ''),
    locator text NOT NULL CHECK (btrim(locator) <> ''),

    locator_resolved boolean NOT NULL,
    quote_matched boolean NOT NULL,
    tier_permitted boolean NOT NULL,
    license_permitted boolean NOT NULL,

    -- What failed, factually. Never composed prose telling Python how to fix an
    -- answer: this row travels back on the regeneration as
    -- `AnswerRequest.previous_failures`, and `Confidence.reason` is the only
    -- Go-authored string in the system.
    failure_detail text NOT NULL DEFAULT '',

    FOREIGN KEY (request_id, attempt)
        REFERENCES trace.traces (request_id, attempt) ON DELETE CASCADE,

    -- Empty exactly when every check passed. A failed check with no detail is a
    -- verification failure nobody can act on, and a passing row carrying a
    -- detail is a failure that got recorded as a pass.
    CONSTRAINT verification_results_detail_iff_failure
        CHECK ((locator_resolved AND quote_matched AND tier_permitted AND license_permitted)
               = (btrim(failure_detail) = ''))
);

CREATE INDEX verification_results_request_idx
    ON trace.verification_results (request_id, attempt);

-- Re-asserted for the same reason the corpus grants are.
GRANT SELECT, INSERT, UPDATE, DELETE
    ON trace.responses, trace.traces, trace.candidates, trace.verification_results TO gateway;

-- catena is granted nothing here and is never granted USAGE on this schema.
