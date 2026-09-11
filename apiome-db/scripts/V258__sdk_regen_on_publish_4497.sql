-- Auto-regen on publish — SDK-4.3 (#4497).
--
-- SDK-4.1 (V256) publishes an SDK to a registry and SDK-4.2 (V257) delivers one as a pull request,
-- but both happen only when somebody remembers to ask. This migration is the durable half of
-- watch mode: a tenant subscribes a project's SDK to its publish events, and every publish expands
-- those subscriptions into jobs a worker runs.
--
--   sdk_regen_subscriptions — which of a project's SDKs regenerate on publish, and how they ship.
--   sdk_regen_runs          — one row per publish event that had at least one active subscription.
--   sdk_regen_jobs          — one row per subscription in that event's matrix: its attempts, its
--                             retry schedule, its dead-letter state, and what it delivered.
--
-- Six rules shape the schema:
--
--   1. **One subscription per project per ecosystem.** The SDK-4.2 target and the SDK-4.1
--      credential are already one per project per ecosystem, and the delivery mode says which of
--      them a regen uses (`registry`, `git`, or both). Two subscriptions for one ecosystem could
--      each claim a registry version for the same publish; one subscription publishing first and
--      delivering the version it claimed cannot.
--
--   2. **A run is the publish event; a job is one cell of its matrix.** The run is written in the
--      same transaction as its jobs, and only when there is at least one active subscription, so a
--      project that subscribes to nothing costs a publish one empty query and no rows.
--
--   3. **A job carries its own queue state.** `pending` → `running` → `succeeded`, or `retrying`
--      after a transient failure (with `next_attempt_at` as the backoff), or `dead_letter` once a
--      failure is permanent or the attempts are spent — the push-webhook delivery lifecycle
--      (#2588), plus `cancelled` for a job that must not run (its subscription was disabled or
--      removed, or its version unpublished). A dead-lettered job is retried by resetting it to
--      `pending`; nothing is ever deleted to retry it.
--
--   4. **One subscription's failure never blocks another's.** Jobs are claimed one at a time with
--      `FOR UPDATE SKIP LOCKED`, and the only ordering rule the claim applies is *within* a
--      subscription (an earlier publish's job goes first), so a job stuck retrying holds back only
--      that subscription's later jobs.
--
--   5. **The job links the event to what it produced.** `publish_run_id` and `delivery_run_id`
--      point at the SDK-4.1 and SDK-4.2 ledgers, and the coordinates a reader wants at a glance —
--      the package version, the artifact digest, the pull request — are copied onto the job, so the
--      history reads "publish of 1.4.2 → npm job → @acme/widgets@1.4.0 + PR #42" in one query.
--
--   6. **Unsubscribing stops future runs and touches nothing past.** `subscription_id` is
--      `ON DELETE SET NULL`, and so are the run and delivery references; a job keeps its own copy of
--      the ecosystem, mode and options it ran with. `project_id` and `tenant_id` cascade.
--
-- **No new credential and no new RBAC resource.** A job authenticates exactly as a manual SDK-4.1
-- publish or SDK-4.2 delivery does. Subscribing is `projects:edit` plus `versions:publish` (a
-- subscription publishes on the tenant's behalf later); reading history is `versions:view` — the
-- argument V254 (CTG-4.5), V255 (SDK-3.4), V256 (SDK-4.1) and V257 (SDK-4.2) made.
--
-- **No retention job.** Like `sdk_publish_runs` and `sdk_git_delivery_runs`, a job row is a few
-- kilobytes and is the record that a publish was delivered; its `attempts` log is capped by the
-- application.
--
-- Rollback notes (reverse carefully in shared environments):
--   DROP TABLE IF EXISTS apiome.sdk_regen_jobs;
--   DROP TABLE IF EXISTS apiome.sdk_regen_runs;
--   DROP TABLE IF EXISTS apiome.sdk_regen_subscriptions;

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- sdk_regen_subscriptions — which of a project's SDKs regenerate on publish, and how they ship.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sdk_regen_subscriptions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,

    -- The language target: the SDK-4.1 package layouts. `gomod` is absent for the reason it is
    -- absent from V256 and V257 — there is no layout to regenerate.
    ecosystem VARCHAR(16) NOT NULL
        CONSTRAINT sdk_regen_subscriptions_ecosystem_check
            CHECK (ecosystem IN ('npm', 'pypi')),

    -- How a regenerated SDK ships: `registry` publishes it (SDK-4.1), `git` opens or updates a pull
    -- request (SDK-4.2), `registry_and_git` publishes first and delivers the version it claimed.
    delivery_mode VARCHAR(24) NOT NULL
        CONSTRAINT sdk_regen_subscriptions_delivery_mode_check
            CHECK (delivery_mode IN ('registry', 'git', 'registry_and_git')),

    -- Per-subscription options, validated by the application against a closed vocabulary
    -- (`dryRun` for the registry step). An object, so an option can be added without a migration.
    options JSONB NOT NULL DEFAULT '{}'::jsonb
        CONSTRAINT sdk_regen_subscriptions_options_object_check
            CHECK (jsonb_typeof(options) = 'object'),

    -- Disabling keeps the configuration and stops future runs; deleting removes both.
    active BOOLEAN NOT NULL DEFAULT TRUE,

    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    updated_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Rule 1, enforced.
CREATE UNIQUE INDEX IF NOT EXISTS idx_sdk_regen_subscriptions_project
    ON sdk_regen_subscriptions (tenant_id, project_id, ecosystem);

COMMENT ON TABLE sdk_regen_subscriptions IS
    'SDK-4.3 (#4497): a project''s SDK for one ecosystem, subscribed to the project''s publish '
    'events. Each publish regenerates it and ships it by delivery_mode — a registry publish '
    '(SDK-4.1), a pull request (SDK-4.2), or both.';

COMMENT ON COLUMN sdk_regen_subscriptions.delivery_mode IS
    'registry publishes the regenerated package; git opens or updates a pull request; '
    'registry_and_git publishes first and delivers the version that publish claimed.';

COMMENT ON COLUMN sdk_regen_subscriptions.active IS
    'Whether publishes regenerate this SDK. A disabled subscription keeps its configuration; jobs '
    'already queued for it are cancelled rather than run.';

-- ---------------------------------------------------------------------------------------------------
-- sdk_regen_runs — one row per publish event that expanded into at least one job.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sdk_regen_runs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,

    -- The published revision, kept as provenance if it is later deleted (rule 6).
    version_id UUID REFERENCES versions(id) ON DELETE SET NULL,
    version_line TEXT,
    published_by UUID REFERENCES users(id) ON DELETE SET NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Listing a project's regen history, newest first.
CREATE INDEX IF NOT EXISTS idx_sdk_regen_runs_history
    ON sdk_regen_runs (tenant_id, project_id, created_at DESC);

COMMENT ON TABLE sdk_regen_runs IS
    'SDK-4.3 (#4497): one publish event that regenerated at least one subscribed SDK. Its jobs '
    '(sdk_regen_jobs) are the cells of the subscription matrix the publish expanded into.';

-- ---------------------------------------------------------------------------------------------------
-- sdk_regen_jobs — one subscription's regeneration for one publish event.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sdk_regen_jobs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    run_id UUID NOT NULL REFERENCES sdk_regen_runs(id) ON DELETE CASCADE,

    -- Rule 6: unsubscribing leaves the job, which keeps its own copy of what it ran with.
    subscription_id UUID REFERENCES sdk_regen_subscriptions(id) ON DELETE SET NULL,
    ecosystem VARCHAR(16) NOT NULL
        CONSTRAINT sdk_regen_jobs_ecosystem_check CHECK (ecosystem IN ('npm', 'pypi')),
    delivery_mode VARCHAR(24) NOT NULL
        CONSTRAINT sdk_regen_jobs_delivery_mode_check
            CHECK (delivery_mode IN ('registry', 'git', 'registry_and_git')),
    options JSONB NOT NULL DEFAULT '{}'::jsonb
        CONSTRAINT sdk_regen_jobs_options_object_check CHECK (jsonb_typeof(options) = 'object'),

    -- Rule 3: the queue lifecycle.
    status VARCHAR(24) NOT NULL
        CONSTRAINT sdk_regen_jobs_status_check
            CHECK (status IN ('pending', 'running', 'retrying', 'succeeded', 'dead_letter', 'cancelled')),
    attempt_count INTEGER NOT NULL DEFAULT 0
        CONSTRAINT sdk_regen_jobs_attempt_count_check CHECK (attempt_count >= 0),
    next_attempt_at TIMESTAMPTZ,

    -- Set by the claim. The token is what lets a worker close only the attempt it claimed: a job
    -- reclaimed after a manual retry carries a new token, so a stale worker cannot overwrite it.
    claimed_at TIMESTAMPTZ,
    claim_token UUID,

    -- Rule 5: what each delivery step produced. The step statuses are the SDK-4.1 and SDK-4.2 run
    -- statuses, copied so a retry knows which steps already succeeded and must not run again.
    publish_run_id UUID REFERENCES sdk_publish_runs(id) ON DELETE SET NULL,
    publish_status VARCHAR(24)
        CONSTRAINT sdk_regen_jobs_publish_status_check
            CHECK (
                publish_status IS NULL
                OR publish_status IN ('in_progress', 'published', 'already_published', 'failed', 'dry_run')
            ),
    delivery_run_id UUID REFERENCES sdk_git_delivery_runs(id) ON DELETE SET NULL,
    delivery_status VARCHAR(24)
        CONSTRAINT sdk_regen_jobs_delivery_status_check
            CHECK (
                delivery_status IS NULL
                OR delivery_status IN ('in_progress', 'opened', 'updated', 'unchanged', 'up_to_date', 'failed')
            ),

    package_name TEXT,
    package_version VARCHAR(128),
    regen_counter INTEGER
        CONSTRAINT sdk_regen_jobs_counter_check CHECK (regen_counter IS NULL OR regen_counter >= 0),
    artifact_sha256 VARCHAR(71),
    pull_request_number INTEGER
        CONSTRAINT sdk_regen_jobs_pr_number_check
            CHECK (pull_request_number IS NULL OR pull_request_number > 0),
    pull_request_url TEXT,

    -- Why the latest attempt did not succeed: which step, a stable code, and a redacted message.
    error_step VARCHAR(16)
        CONSTRAINT sdk_regen_jobs_error_step_check
            CHECK (error_step IS NULL OR error_step IN ('generate', 'registry', 'git', 'worker')),
    error_code VARCHAR(64),
    error_message TEXT,

    -- One entry per attempt, capped by the application, each naming the publish and delivery runs
    -- it wrote — so a failed attempt stays linked even after a retry succeeds.
    attempts JSONB NOT NULL DEFAULT '[]'::jsonb
        CONSTRAINT sdk_regen_jobs_attempts_array_check CHECK (jsonb_typeof(attempts) = 'array'),

    retry_requested_by UUID REFERENCES users(id) ON DELETE SET NULL,
    retry_requested_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMPTZ
);

-- Rule 2: a publish event regenerates each ecosystem once.
CREATE UNIQUE INDEX IF NOT EXISTS idx_sdk_regen_jobs_run_ecosystem
    ON sdk_regen_jobs (run_id, ecosystem);

-- The claim: "which queued jobs are due?"
CREATE INDEX IF NOT EXISTS idx_sdk_regen_jobs_due
    ON sdk_regen_jobs (next_attempt_at)
    WHERE status IN ('pending', 'retrying');

-- Rule 4: "does this subscription have an earlier job still in flight?"
CREATE INDEX IF NOT EXISTS idx_sdk_regen_jobs_subscription_active
    ON sdk_regen_jobs (subscription_id, created_at)
    WHERE status IN ('pending', 'running', 'retrying');

-- The lease sweep: "which running jobs has no worker finished?"
CREATE INDEX IF NOT EXISTS idx_sdk_regen_jobs_running
    ON sdk_regen_jobs (claimed_at)
    WHERE status = 'running';

-- The dead-letter listing.
CREATE INDEX IF NOT EXISTS idx_sdk_regen_jobs_dead_letter
    ON sdk_regen_jobs (tenant_id, project_id, updated_at DESC)
    WHERE status = 'dead_letter';

COMMENT ON TABLE sdk_regen_jobs IS
    'SDK-4.3 (#4497): one subscription''s regeneration for one publish event — its queue state, '
    'its attempts, and the SDK-4.1 publish run and SDK-4.2 delivery run it produced. A permanently '
    'failed job is dead_letter and is retried by resetting it to pending.';

COMMENT ON COLUMN sdk_regen_jobs.status IS
    'pending is queued; running is claimed by a worker; retrying waits for next_attempt_at after a '
    'transient failure; succeeded delivered every configured step; dead_letter failed permanently '
    'or spent its attempts and waits for a manual retry; cancelled must not run (its subscription '
    'was disabled or removed, or its version unpublished).';

COMMENT ON COLUMN sdk_regen_jobs.claim_token IS
    'A fresh token per claim. A worker closes an attempt only if the token still matches, so a '
    'worker that outlived its lease cannot overwrite a job that was retried and reclaimed.';

COMMENT ON COLUMN sdk_regen_jobs.attempts IS
    'Ordered attempt records, each {attempt, startedAt, finishedAt, outcome, errorStep, errorCode, '
    'publishRunId, publishStatus, deliveryRunId, deliveryStatus}. Capped by the application.';
