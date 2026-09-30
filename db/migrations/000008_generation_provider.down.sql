-- Dropping the columns loses the attribution and nothing else: no row depends on
-- them, so unlike 000007 this rollback destroys no turns.
ALTER TABLE trace.traces
    DROP CONSTRAINT IF EXISTS traces_generation_provider_not_blank,
    DROP COLUMN IF EXISTS schema_delivery,
    DROP COLUMN IF EXISTS generation_provider;

DROP TYPE IF EXISTS trace.schema_delivery;
