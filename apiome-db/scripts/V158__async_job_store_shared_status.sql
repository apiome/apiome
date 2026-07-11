-- Shared status store for async jobs (spec-import + export).
--
-- Both the spec-import engine and the export engine tracked job state in a per-process,
-- in-memory dict. Under a round-robin deployment (several REST instances behind a load
-- balancer) the POST that creates a job lands on one instance, but the follow-up status
-- polls are balanced across all of them — so the instances that never saw the POST answer
-- `404 "… job not found"`, killing the import/export from the client's point of view.
--
-- This table is the shared read model: the instance driving a job mirrors its poll payload
-- here on every state change, and any instance answers GET/list from it. The driving instance
-- still owns the live work (subprocess / pipeline); only the *reads* are shared. `job_id` is
-- text (not uuid) so a malformed id in a URL yields a clean 404 instead of a cast error.
SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS apiome.async_job (
    job_id            text PRIMARY KEY,
    kind              text NOT NULL,                 -- 'spec_import' | 'export'
    tenant_slug       text NOT NULL,
    state             text NOT NULL,                 -- queued | running | completed | failed | canceled | …
    status            jsonb NOT NULL,                -- serialized *JobStatus poll payload
    extra             jsonb,                         -- per-kind bag: import commit payload; export list metadata
    cancel_requested  boolean NOT NULL DEFAULT false, -- set cross-instance; honored by the driver
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now()
);

-- List endpoints scope by (tenant, kind); newest first.
CREATE INDEX IF NOT EXISTS async_job_tenant_kind_idx
    ON apiome.async_job (tenant_slug, kind, created_at DESC);

-- Supports a future retention sweep that reaps old terminal jobs.
CREATE INDEX IF NOT EXISTS async_job_updated_at_idx
    ON apiome.async_job (updated_at);
