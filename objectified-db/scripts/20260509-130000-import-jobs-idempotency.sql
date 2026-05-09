-- Import jobs: optional Idempotency-Key for POST /v1/imports/{tenant_slug} (#3306)
SET search_path TO odb, public;

ALTER TABLE odb.import_jobs
    ADD COLUMN IF NOT EXISTS idempotency_key TEXT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS import_jobs_tenant_idempotency_key_udx
    ON odb.import_jobs (tenant_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;

COMMENT ON COLUMN odb.import_jobs.idempotency_key IS
    'Optional client Idempotency-Key (HTTP header); collisions within 24h return the same job (#3306)';

-- DOWN
-- ALTER TABLE odb.import_jobs DROP COLUMN IF EXISTS idempotency_key;
