ALTER TABLE trace.responses
    DROP CONSTRAINT IF EXISTS responses_confidence_reason_not_blank,
    DROP CONSTRAINT IF EXISTS responses_generation_failed_is_second_attempt,
    DROP CONSTRAINT IF EXISTS responses_confidence_absent_iff_generation_failed,
    DROP CONSTRAINT IF EXISTS responses_answer_absent_iff_generation_failed;

-- Rows with a NULL answer cannot survive the NOT NULL coming back, and they are
-- exactly the rows this feature added. Deleting them is correct for a rollback
-- and is stated rather than left to a constraint violation at 3am.
DELETE FROM trace.responses WHERE answer IS NULL;

ALTER TABLE trace.responses
    ADD CONSTRAINT responses_confidence_reason_check
        CHECK (btrim(confidence_reason) <> ''),
    ALTER COLUMN confidence_reason SET NOT NULL,
    ALTER COLUMN confidence_level SET NOT NULL,
    ALTER COLUMN answer SET NOT NULL;

DROP TABLE IF EXISTS trace.generation_failures;
DROP TYPE IF EXISTS trace.generation_failure_code;
