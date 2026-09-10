ALTER TABLE trace.responses DROP CONSTRAINT IF EXISTS responses_degraded_is_second_attempt;

DROP TABLE IF EXISTS trace.answer_failures;

DROP TYPE IF EXISTS trace.answer_failure_code;
