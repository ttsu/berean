ALTER TABLE trace.traces DROP COLUMN IF EXISTS verify_us;

ALTER TABLE trace.responses DROP COLUMN IF EXISTS gateway_version;
