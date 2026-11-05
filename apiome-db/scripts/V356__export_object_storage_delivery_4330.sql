-- Export object-storage delivery — MFX-38.3 (#4330).
--
-- Data platforms expect artifacts in buckets with a predictable layout. Object-storage delivery
-- uploads a completed export job's bundle to an S3-compatible bucket (AWS S3, MinIO, Cloudflare R2,
-- Ceph, …) under a configured prefix partitioned by artifact / version / target, with a
-- content-addressed manifest. Two tables:
--
--   1. `export_storage_credentials` — the tenant's bucket credentials, in the credential vault: an
--      access key pair (and optional session token) sealed by the envelope `mcp_endpoint_credentials`
--      and `catalog_connector_credentials` use (`app.mcp_credential_crypto`, AES-256-GCM). Ciphertext
--      only; no route reads it back. The non-secret parts — the endpoint, region, addressing style and
--      the access key id's last four characters, so a person can tell keys apart — are cleartext.
--
--   2. `export_object_storage_delivery_runs` — one row per delivery: where it wrote (bucket and the
--      resolved key prefix), every object with its size and SHA-256, the manifest's key and hash, and
--      the outcome. A failed run is kept with a stable `error_code`.
--
-- Four rules shape them:
--
--   * **Secrets never leave the vault.** `encrypted_payload` is the only column holding secret
--     material; runs copy nothing from it. Error messages are redacted before they are stored.
--   * **Tenant-scoped.** A credential belongs to one tenant and is named uniquely within it; a run
--     names its credential `ON DELETE SET NULL` and copies the bucket and prefix, so deleting a
--     credential never deletes history.
--   * **Keys stay inside the prefix.** `key_prefix` is stored normalised (no leading `/`, no `..`
--     segment) — the CHECK repeats the application's rule.
--   * **Failures are runs.** A run is inserted `in_progress` before the first upload and closed
--     `delivered` or `failed`.
--
-- **No new RBAC resource.** Managing a storage credential is `projects:edit` (listing:
-- `projects:view`), as a tenant package-registry credential (SDK-4.1) is; delivering is
-- `versions:publish`, as a git (MFX-38.1) or webhook (MFX-38.2) delivery is.
--
-- Rollback notes (reverse carefully in shared environments):
--   DROP TABLE IF EXISTS apiome.export_object_storage_delivery_runs;
--   DROP TABLE IF EXISTS apiome.export_storage_credentials;

SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS export_storage_credentials (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    name VARCHAR(120) NOT NULL,

    -- Only the S3 API today; the column leaves room for others.
    provider VARCHAR(16) NOT NULL DEFAULT 's3'
        CONSTRAINT export_storage_credentials_provider_check CHECK (provider IN ('s3')),

    -- NULL means AWS S3's own endpoints; otherwise an http(s) S3-compatible endpoint.
    endpoint_url TEXT
        CONSTRAINT export_storage_credentials_endpoint_check
            CHECK (endpoint_url IS NULL OR endpoint_url ~* '^https?://'),
    region VARCHAR(64) NOT NULL DEFAULT 'us-east-1',
    force_path_style BOOLEAN NOT NULL DEFAULT FALSE,

    -- The access key id's last four characters, for telling keys apart. Never the whole id.
    access_key_hint VARCHAR(4) NOT NULL,

    -- The sealed {accessKeyId, secretAccessKey, sessionToken?}. Never plaintext.
    encrypted_payload BYTEA NOT NULL,
    key_version INTEGER NOT NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,

    CONSTRAINT export_storage_credentials_name_unique UNIQUE (tenant_id, name)
);

COMMENT ON TABLE export_storage_credentials IS
    'MFX-38.3 (#4330): a tenant''s S3-compatible bucket credentials for export delivery. The access key '
    'pair is sealed (app.mcp_credential_crypto) in encrypted_payload; write-only — no route reads it back.';

CREATE TABLE IF NOT EXISTS export_object_storage_delivery_runs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    -- What was exported, without foreign keys that would make the record disappear.
    job_id VARCHAR(64) NOT NULL,
    artifact_id VARCHAR(64) NOT NULL,
    version_record_id VARCHAR(64),
    version_label TEXT,
    export_target VARCHAR(128),

    credential_id UUID REFERENCES export_storage_credentials(id) ON DELETE SET NULL,
    endpoint_url TEXT,
    bucket VARCHAR(63) NOT NULL,

    -- The resolved prefix every object was written under (configured prefix + partitions).
    key_prefix TEXT NOT NULL DEFAULT ''
        CONSTRAINT export_object_storage_delivery_runs_prefix_check
            CHECK (
                key_prefix !~ '^/'
                AND key_prefix !~ '(^|/)\.\.?(/|$)'
                AND key_prefix !~ '//'
                AND key_prefix !~ '\\'
            ),
    partitioning JSONB NOT NULL DEFAULT '[]'::jsonb
        CONSTRAINT export_object_storage_delivery_runs_partitioning_check CHECK (jsonb_typeof(partitioning) = 'array'),

    status VARCHAR(16) NOT NULL
        CONSTRAINT export_object_storage_delivery_runs_status_check
            CHECK (status IN ('in_progress', 'delivered', 'failed')),

    -- Every object written: {key, sizeBytes, sha256, contentType}.
    objects JSONB NOT NULL DEFAULT '[]'::jsonb
        CONSTRAINT export_object_storage_delivery_runs_objects_array_check CHECK (jsonb_typeof(objects) = 'array'),
    manifest_key TEXT,
    manifest_sha256 VARCHAR(64),

    fidelity JSONB NOT NULL DEFAULT '{}'::jsonb
        CONSTRAINT export_object_storage_delivery_runs_fidelity_object_check CHECK (jsonb_typeof(fidelity) = 'object'),

    error_code VARCHAR(64),
    error_message TEXT,

    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMPTZ,
    created_by UUID REFERENCES users(id) ON DELETE SET NULL
);

-- A job's deliveries, newest first.
CREATE INDEX IF NOT EXISTS idx_export_object_storage_delivery_runs_job
    ON export_object_storage_delivery_runs (tenant_id, job_id, started_at DESC);

COMMENT ON TABLE export_object_storage_delivery_runs IS
    'MFX-38.3 (#4330): one row per export object-storage delivery — the bucket and key prefix, every '
    'object with its SHA-256, the content-addressed manifest, and the outcome. A failed run is kept with '
    'its error code; no secret is copied here.';

COMMENT ON COLUMN export_object_storage_delivery_runs.manifest_key IS
    'The immutable, content-addressed manifest (<prefix>/manifests/<sha256>.json); <prefix>/manifest.json '
    'is a copy that always names the latest delivery to that prefix.';
