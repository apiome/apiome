-- Auto-export on version publish — MFX-39.4 (#4336).
--
-- Downstream consumers — a git repository, a registry, a bucket — drift the moment a new version
-- publishes. An **auto-export subscription** binds an export preset (MFX-39.3) to a project: every
-- publish of that project runs the preset's export and, through the preset's delivery profile
-- (MFX-38.4), delivers it — unless the export loses too much. Three changes:
--
--   1. `export_auto_subscriptions` — one row per (project, preset): `halt_at`, the loss severity at
--      which auto-delivery stops (`warn` or `critical`), and `approve_loss`, the pre-approval that lets a
--      lossy export through anyway. Off (`active = false`) keeps the row and its history.
--
--   2. `export_auto_runs` — one row per (publish × subscription): queued by the publish, claimed by the
--      sweep (`FOR UPDATE SKIP LOCKED`), and closed `delivered`, `exported` (no delivery profile),
--      `halted` (the loss reached `halt_at` — nothing was delivered and people were told), `delivery_failed`
--      or `failed`. The run keeps the export job id, the loss it measured and why, and every delivery's
--      outcome, so it is the audit record of what an auto-export did.
--
--   3. A new inbox type, `export_auto_halted`, for the people a halted (or failed) auto-export tells.
--
-- Four rules shape them:
--
--   * **A publish never fails because of a subscription.** The publish only queues rows, after its
--     response, and a queueing error is logged, not raised.
--   * **History outlives configuration.** Runs name their subscription and preset `ON DELETE SET NULL`
--     and copy the preset's name; deleting either never deletes a run.
--   * **Attributed to the publisher.** The run keeps `published_by`; deliveries are made, and audited,
--     as that user.
--   * **A halt is a decision someone can reverse.** A halted run keeps its job; `released_by` /
--     `released_at` record who delivered it anyway, while the export's artifact is retained.
--
-- **No new RBAC resource.** Managing a subscription is `projects:edit` plus `versions:publish` (it
-- delivers outside Apiome on every publish), as an SDK regen subscription is; reading is
-- `projects:view`; releasing a halted run is `versions:publish`.
--
-- Rollback notes (reverse carefully in shared environments):
--   DROP TABLE IF EXISTS apiome.export_auto_runs;
--   DROP TABLE IF EXISTS apiome.export_auto_subscriptions;
--   DELETE FROM apiome.notifications WHERE type = 'export_auto_halted';  -- then restore the V286 CHECK

SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS export_auto_subscriptions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    preset_id UUID NOT NULL REFERENCES export_presets(id) ON DELETE CASCADE,

    -- Auto-delivery halts when the export's loss reaches this severity (MFX-2.4 vocabulary).
    halt_at VARCHAR(16) NOT NULL DEFAULT 'critical'
        CONSTRAINT export_auto_subscriptions_halt_at_check CHECK (halt_at IN ('warn', 'critical')),
    -- Pre-approval: deliver even when the loss reaches `halt_at`.
    approve_loss BOOLEAN NOT NULL DEFAULT FALSE,
    active BOOLEAN NOT NULL DEFAULT TRUE,

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    updated_by UUID REFERENCES users(id) ON DELETE SET NULL,

    CONSTRAINT export_auto_subscriptions_unique UNIQUE (tenant_id, project_id, preset_id)
);

-- What a publish looks up: the project's active subscriptions.
CREATE INDEX IF NOT EXISTS idx_export_auto_subscriptions_project
    ON export_auto_subscriptions (tenant_id, project_id) WHERE active;

COMMENT ON TABLE export_auto_subscriptions IS
    'MFX-39.4 (#4336): an export preset run on every publish of a project, delivered unless its loss '
    'reaches halt_at (and approve_loss is off).';

CREATE TABLE IF NOT EXISTS export_auto_runs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    -- The published revision; kept as text so an unpublished or deleted revision keeps its run.
    version_record_id VARCHAR(64) NOT NULL,

    subscription_id UUID REFERENCES export_auto_subscriptions(id) ON DELETE SET NULL,
    preset_id UUID REFERENCES export_presets(id) ON DELETE SET NULL,
    preset_name VARCHAR(120) NOT NULL,
    -- The subscription's rule as it was when the run was queued.
    halt_at VARCHAR(16) NOT NULL
        CONSTRAINT export_auto_runs_halt_at_check CHECK (halt_at IN ('warn', 'critical')),
    approve_loss BOOLEAN NOT NULL DEFAULT FALSE,

    status VARCHAR(16) NOT NULL DEFAULT 'pending'
        CONSTRAINT export_auto_runs_status_check
            CHECK (status IN ('pending', 'running', 'delivered', 'exported', 'halted', 'delivery_failed', 'failed')),

    job_id VARCHAR(64),
    -- The loss the export measured: `info`, `warn` or `critical`, and why.
    loss_severity VARCHAR(16)
        CONSTRAINT export_auto_runs_loss_check CHECK (loss_severity IS NULL OR loss_severity IN ('info', 'warn', 'critical')),
    loss_reasons JSONB NOT NULL DEFAULT '[]'::jsonb
        CONSTRAINT export_auto_runs_reasons_check CHECK (jsonb_typeof(loss_reasons) = 'array'),
    -- One entry per delivery: {profileId, profileName, channel, runId, status, outcome, destination, errorCode}.
    deliveries JSONB NOT NULL DEFAULT '[]'::jsonb
        CONSTRAINT export_auto_runs_deliveries_check CHECK (jsonb_typeof(deliveries) = 'array'),

    error_code VARCHAR(64),
    error_message TEXT,

    published_by UUID REFERENCES users(id) ON DELETE SET NULL,
    released_by UUID REFERENCES users(id) ON DELETE SET NULL,
    released_at TIMESTAMPTZ,

    claim_token UUID,
    claimed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMPTZ
);

-- The sweep's queue, oldest first.
CREATE INDEX IF NOT EXISTS idx_export_auto_runs_pending
    ON export_auto_runs (created_at) WHERE status IN ('pending', 'running');
-- A project's runs, newest first.
CREATE INDEX IF NOT EXISTS idx_export_auto_runs_project
    ON export_auto_runs (tenant_id, project_id, created_at DESC);

COMMENT ON TABLE export_auto_runs IS
    'MFX-39.4 (#4336): one auto-export per publish per subscription — its export job, measured loss, '
    'halt decision and delivery outcomes; the audit record of what an auto-export did.';

-- ---------------------------------------------------------------------------------------------------
-- The inbox type
-- ---------------------------------------------------------------------------------------------------
ALTER TABLE notifications DROP CONSTRAINT IF EXISTS notifications_type_check;
ALTER TABLE notifications
    ADD CONSTRAINT notifications_type_check
        CHECK (type IN (
            'mention', 'review_requested', 'review_decision', 'thread_resolved', 'version_published',
            'export_auto_halted',
            'owner_finding', 'owner_breaking_change', 'owner_verification_drift', 'owner_gate_blocked',
            'owner_trust_drift', 'owner_shadow_api', 'owner_sync_failed'
        ));

COMMENT ON COLUMN notifications.type IS
    'mention | review_requested | review_decision | thread_resolved | version_published | export_auto_halted | owner_finding | owner_breaking_change | owner_verification_drift | owner_gate_blocked | owner_trust_drift | owner_shadow_api | owner_sync_failed';
