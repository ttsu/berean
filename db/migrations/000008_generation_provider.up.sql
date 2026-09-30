-- Which provider answered, and what its request enforced of the answer schema.
--
-- ADR-0018 pinned the generator because "an unpinned generator makes the Phase 2
-- number unreproducible." Four providers do not break that, on the condition
-- that a run can be attributed: `generation_model` alone cannot tell two
-- enforcement regimes of one model apart, and that becomes live the moment a
-- probe reclassifies a provider (ADR-0026).
--
-- One migration, unlike 000006/000007. That pair was split because Postgres
-- forbids using a new enum *value* in the transaction that added it; creating a
-- type and using it in the same transaction is fine.
CREATE TYPE trace.schema_delivery AS ENUM (
    'constrained',
    'shaped',
    'unconstrained'
);

ALTER TABLE trace.traces
    ADD COLUMN generation_provider text,
    ADD COLUMN schema_delivery trace.schema_delivery;

-- Every row that already exists was written by the one provider this project
-- shipped before this migration, under the one mode that provider enforces.
-- Backfilling the fact is what lets these be NOT NULL without inventing history
-- the Phase 2 harness would go on to average.
UPDATE trace.traces
   SET generation_provider = 'ollama',
       schema_delivery = 'constrained'
 WHERE generation_provider IS NULL;

ALTER TABLE trace.traces
    ALTER COLUMN generation_provider SET NOT NULL,
    ALTER COLUMN schema_delivery SET NOT NULL,
    -- A provider of three spaces satisfies NOT NULL while recording exactly the
    -- unattributed run the column exists to prevent, which is why both sides
    -- trim.
    ADD CONSTRAINT traces_generation_provider_not_blank
        CHECK (btrim(generation_provider) <> '');

-- Re-asserted for the same reason every other grant in this schema is.
GRANT SELECT, INSERT, UPDATE, DELETE ON trace.traces TO gateway;

-- catena is granted nothing here and is never granted USAGE on this schema.
