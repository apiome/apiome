-- Export webhook delivery runs — MFX-38.2 (#4329).
--
-- Pipelines want to be told when an export is ready, with the result, rather than poll for a
-- download. A webhook delivery POSTs a completed export job's result — the file manifest, the
-- fidelity report, and the bundle itself (inline, or as a signed fetch link when it is large) — to a
-- URL, signed with HMAC-SHA256, retried with backoff. This table is the record of every delivery and
-- every attempt it made.
--
-- Five rules shape it:
--
--   1. **The signing secret is never stored.** The caller hands the shared secret with the request;
--      the body is signed once, there and then, and the exact signed bytes (`payload`) and their
--      signature are kept so every retry re-sends byte-identical, still-verifiable content. There is
--      no secret column: a database reader cannot sign anything new.
--
--   2. **Configuration rides on the request, not in a table.** Where the result goes is given with
--      each delivery; MFX-38.4 (#4331) adds saved delivery profiles. Each run copies its URL so the
--      record stands on its own (the API shows it without its query string, which may carry a token).
--
--   3. **Failures are runs, not missing rows.** A run is inserted `delivering` before the first
--      attempt and closed `delivered` or `failed` with an `error_code`; in between it is `retrying`
--      with a `next_attempt_at` the delivery sweep picks up (`pending` is a run waiting for the sweep).
--
--   4. **Every attempt is kept.** `attempts` is an ordered array of {attempt, at, httpStatus,
--      latencyMs, error, responsePreview} — the receiver's own answer, capped.
--
--   5. **A run outlives nothing it should not.** It goes with its tenant; the exported artifact can be
--      a project or a catalog item, so `artifact_id` has no foreign key; the export job lives in the
--      shared job store, keyed by `job_id`.
--
-- **No new RBAC resource.** Sending an export outside the workspace is `versions:publish`, as a git
-- delivery (MFX-38.1) or an SDK delivery (SDK-4.2) is.
--
-- Rollback notes (reverse carefully in shared environments):
--   DROP TABLE IF EXISTS apiome.export_webhook_delivery_runs;

SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS export_webhook_delivery_runs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    -- Rule 5: what was exported, without foreign keys that would make the record disappear.
    job_id VARCHAR(64) NOT NULL,
    artifact_id VARCHAR(64) NOT NULL,
    version_record_id VARCHAR(64),
    version_label TEXT,
    export_target VARCHAR(128),

    -- Rule 2: http or https only (the application's SSRF guard checks the rest, on every attempt).
    target_url TEXT NOT NULL
        CONSTRAINT export_webhook_delivery_runs_url_check CHECK (target_url ~* '^https?://'),

    -- Rule 3.
    status VARCHAR(16) NOT NULL
        CONSTRAINT export_webhook_delivery_runs_status_check
            CHECK (status IN ('pending', 'delivering', 'retrying', 'delivered', 'failed')),

    -- How the bundle travels: in the body, or as a signed fetch link.
    artifact_delivery VARCHAR(8) NOT NULL
        CONSTRAINT export_webhook_delivery_runs_artifact_check CHECK (artifact_delivery IN ('inline', 'fetch')),

    -- Rule 1: the exact signed body and its `sha256=<hex>` signature; never the secret.
    payload BYTEA NOT NULL,
    payload_sha256 VARCHAR(64) NOT NULL,
    signature VARCHAR(80) NOT NULL
        CONSTRAINT export_webhook_delivery_runs_signature_check CHECK (signature ~ '^sha256=[0-9a-f]{64}$'),

    -- The export's fidelity summary (tier, preserved share, counts), for the run list.
    fidelity JSONB NOT NULL DEFAULT '{}'::jsonb
        CONSTRAINT export_webhook_delivery_runs_fidelity_object_check CHECK (jsonb_typeof(fidelity) = 'object'),

    -- Rule 4.
    attempt_count INTEGER NOT NULL DEFAULT 0
        CONSTRAINT export_webhook_delivery_runs_attempt_count_check CHECK (attempt_count >= 0),
    max_attempts INTEGER NOT NULL
        CONSTRAINT export_webhook_delivery_runs_max_attempts_check CHECK (max_attempts > 0),
    attempts JSONB NOT NULL DEFAULT '[]'::jsonb
        CONSTRAINT export_webhook_delivery_runs_attempts_array_check CHECK (jsonb_typeof(attempts) = 'array'),
    next_attempt_at TIMESTAMPTZ,
    last_http_status INTEGER,

    error_code VARCHAR(64),
    error_message TEXT,

    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMPTZ,
    created_by UUID REFERENCES users(id) ON DELETE SET NULL
);

-- A job's deliveries, newest first.
CREATE INDEX IF NOT EXISTS idx_export_webhook_delivery_runs_job
    ON export_webhook_delivery_runs (tenant_id, job_id, started_at DESC);

-- What the delivery sweep claims: runs waiting for their next attempt.
CREATE INDEX IF NOT EXISTS idx_export_webhook_delivery_runs_due
    ON export_webhook_delivery_runs (next_attempt_at)
    WHERE status IN ('pending', 'retrying');

COMMENT ON TABLE export_webhook_delivery_runs IS
    'MFX-38.2 (#4329): one row per export webhook delivery — the signed body sent (never the secret), '
    'the destination, every attempt with the receiver''s answer, and the outcome. A failed run is kept '
    'with its error code.';

COMMENT ON COLUMN export_webhook_delivery_runs.status IS
    'pending waits for the delivery sweep; delivering has an attempt in flight; retrying failed an '
    'attempt and waits for next_attempt_at; delivered got a 2xx; failed was refused, rejected (a 3xx or '
    '4xx other than 408/425/429) or ran out of attempts, and names its reason in error_code.';

COMMENT ON COLUMN export_webhook_delivery_runs.payload IS
    'The exact signed request body. Retries re-send these bytes with the stored signature, so the '
    'receiver can verify every attempt and de-duplicate on X-Apiome-Delivery.';
