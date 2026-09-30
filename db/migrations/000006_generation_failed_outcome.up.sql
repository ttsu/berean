-- The fourth outcome: the generator produced no answer object across both
-- attempts. Alone in its own migration because Postgres forbids using a new
-- enum value in the transaction that added it, and 000007's CHECK constraints
-- cast this literal at DDL time.
ALTER TYPE trace.overall_result ADD VALUE IF NOT EXISTS 'generation-failed';
