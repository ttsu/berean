-- The answer-level failures, and the one thing Task 3 deliberately left open.
--
-- `trace.verification_results` is shaped for the four checks: one row per
-- citation, four booleans, and a detail that is empty exactly when all four
-- passed. Several of the rules the trust boundary enforces are about a *slot*
-- rather than a citation — an argument with nothing behind it, a position
-- stated where nothing was argued, a locus flagged contested and resolved
-- anyway — and the omission check is sharper still: every one of the four
-- checks passes and the answer fails. None of those can be written as a
-- verification result without a row whose booleans all say "passed" beside a
-- detail saying the answer did not (ADR-0024).

-- Closed, like every other domain in this schema. The values are the proto's
-- `AnswerFailureCode` without its prefix; the enum is what makes "how often did
-- the generator resolve a contested locus" a GROUP BY rather than a LIKE.
CREATE TYPE trace.answer_failure_code AS ENUM (
    'citations-required',
    'argument-lacks-authority',
    'position-without-arguments',
    'contested-with-arguments',
    'contested-locus-unknown',
    'contested-ruling-uncited',
    'contested-ruling-unquoted',
    'ruling-cited-while-uncontested',
    'state-of-debate-without-contest',
    'no-answer-reason-not-alone',
    'no-answer-reason-too-long',
    'empty-answer'
);

-- One row per broken rule per attempt.
CREATE TABLE trace.answer_failures (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    request_id uuid NOT NULL,
    attempt smallint NOT NULL,

    code trace.answer_failure_code NOT NULL,
    -- Where, in the answer object's own terms: `arguments[2]`,
    -- `contested.locus`, `no_answer_reason`. Never blank: a rule that broke
    -- somewhere unrecorded is a finding nobody can chase.
    slot text NOT NULL CHECK (btrim(slot) <> ''),

    -- The citation the rule is about, when one is. Empty for the rules that are
    -- about a slot's emptiness rather than about anything in it, which is why
    -- these are plain columns with a default rather than NOT NULL — and, as on
    -- `verification_results`, no foreign key into `corpus`: the omission check
    -- names a citation precisely because it resolved, but the surrounding
    -- table must stay able to record one that did not.
    corpus_id text NOT NULL DEFAULT '',
    locator text NOT NULL DEFAULT '',

    -- What broke, factually. Never composed prose telling Python how to fix an
    -- answer: this row travels back on the regeneration as
    -- `AnswerRequest.answer_failures`, and `Confidence.reason` is still the
    -- only Go-authored string in the system.
    detail text NOT NULL CHECK (btrim(detail) <> ''),

    FOREIGN KEY (request_id, attempt)
        REFERENCES trace.traces (request_id, attempt) ON DELETE CASCADE,

    -- Half a citation reference is not one. A `corpus_id` with no locator
    -- resolves to a whole corpus, which is not a thing any rule here is about.
    CONSTRAINT answer_failures_ref_is_whole_or_absent
        CHECK ((btrim(corpus_id) = '') = (btrim(locator) = ''))
);

CREATE INDEX answer_failures_request_idx ON trace.answer_failures (request_id, attempt);

-- Phase 2 asks "which rule does this generator break most often", and asks it
-- across every turn rather than within one.
CREATE INDEX answer_failures_code_idx ON trace.answer_failures (code);

-- Task 3 left `degraded` free on attempt count, saying whether an unretryable
-- failure degrades at one attempt or two was Task 8's to decide. It is decided:
-- **always two**. DEGRADED means verification refused to ship, which is a
-- successful outcome of the verification system; an unreachable Catena or an
-- unreachable database is a failure of the system, and the gateway surfaces
-- that as an error rather than laundering it into the degradation rate ADR-0010
-- needs kept clean. Nothing else can reach degradation without two generation
-- attempts, so the invariant is now holdable and is held.
ALTER TABLE trace.responses
    ADD CONSTRAINT responses_degraded_is_second_attempt
    CHECK (overall_result <> 'degraded' OR attempts = 2);

-- Re-asserted for the same reason every other grant in this schema is.
GRANT SELECT, INSERT, UPDATE, DELETE ON trace.answer_failures TO gateway;

-- catena is granted nothing here and is never granted USAGE on this schema.
