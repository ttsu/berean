-- The fourth outcome: the turn's final attempt produced no answer object
-- (decided by the final attempt only — an earlier attempt may have been
-- checked and failed). Alone in its own migration because Postgres forbids
-- using a new enum value in the transaction that added it, and 000007's CHECK
-- constraints cast this literal at DDL time.
ALTER TYPE trace.overall_result ADD VALUE IF NOT EXISTS 'generation-failed';
