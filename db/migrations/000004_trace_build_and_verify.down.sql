ALTER TABLE trace.traces DROP COLUMN IF EXISTS verify_ms;

ALTER TABLE trace.responses DROP COLUMN IF EXISTS gateway_version;
