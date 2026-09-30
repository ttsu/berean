-- Why no answer object was produced, one row per attempt. The upstream sibling
-- of trace.answer_failures: that table names the slot a rule broke in, and a
-- generation with no object has no slots (ADR-0024, ADR-0025).
CREATE TYPE trace.generation_failure_code AS ENUM (
    'truncated',
    'context-exhausted',
    'not-json',
    'not-an-object',
    'empty',
    'provider-refused'
);

CREATE TABLE trace.generation_failures (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    request_id uuid NOT NULL,
    attempt smallint NOT NULL,

    code trace.generation_failure_code NOT NULL,

    -- What happened, factually. Never the model's account of its own
    -- reasoning: for 'provider-refused' this is the provider's category and
    -- never its explanation (CLAUDE.md constraint 5).
    detail text NOT NULL CHECK (btrim(detail) <> ''),

    -- How far the attempt got. Zero when it produced nothing.
    completion_tokens integer NOT NULL DEFAULT 0 CHECK (completion_tokens >= 0),

    FOREIGN KEY (request_id, attempt)
        REFERENCES trace.traces (request_id, attempt) ON DELETE CASCADE
);

CREATE INDEX generation_failures_code_idx ON trace.generation_failures (code);

-- A turn that produced no answer object has no answer and no confidence, and
-- both absences have to be recordable as absences.
--
-- `answer` is nullable rather than storing '{}'. An answer object with every
-- slot empty IS the honest-silence shape -- the corpus was asked and had
-- nothing to say -- so writing '{}' here would encode a truncation as
-- considered silence in the one table the Phase 2 harness reads, which is a
-- worse bug than the one being fixed (ADR-0020).
--
-- `confidence` follows it. Go derives confidence from the verification result
-- and there was no verification, so a synthetic 'low' would be a number the
-- harness could average without knowing it was invented.
ALTER TABLE trace.responses
    ALTER COLUMN answer DROP NOT NULL,
    ALTER COLUMN confidence_level DROP NOT NULL,
    ALTER COLUMN confidence_reason DROP NOT NULL;

-- The absences and the outcome are one fact, so they cannot be recorded apart.
ALTER TABLE trace.responses
    ADD CONSTRAINT responses_answer_absent_iff_generation_failed
        CHECK ((answer IS NULL) = (overall_result = 'generation-failed')),
    ADD CONSTRAINT responses_confidence_absent_iff_generation_failed
        CHECK ((confidence_level IS NULL) = (overall_result = 'generation-failed')
               AND (confidence_reason IS NULL) = (overall_result = 'generation-failed')),
    -- Symmetric with responses_degraded_is_second_attempt: a generation failure
    -- consumes the one regeneration ADR-0010 grants, so it always follows two.
    ADD CONSTRAINT responses_generation_failed_is_second_attempt
        CHECK (overall_result <> 'generation-failed' OR attempts = 2);

-- The non-blank check has to stop applying to NULL, which it already does, but
-- the original column carried it as a column constraint on a NOT NULL column.
-- Restated so a blank string is still rejected when a reason is present.
ALTER TABLE trace.responses
    DROP CONSTRAINT IF EXISTS responses_confidence_reason_check,
    ADD CONSTRAINT responses_confidence_reason_not_blank
        CHECK (confidence_reason IS NULL OR btrim(confidence_reason) <> '');

-- Re-asserted for the same reason every other grant in this schema is.
GRANT SELECT, INSERT, UPDATE, DELETE ON trace.generation_failures TO gateway;

-- catena is granted nothing here and is never granted USAGE on this schema.
