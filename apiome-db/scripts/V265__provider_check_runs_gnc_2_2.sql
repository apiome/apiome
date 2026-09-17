-- Provider webhook and status adapter — GNC-2.2 (#4738).
--
-- GNC-2.1 (V264) gave a draft a durable relationship to a repository ref, and a push to that ref
-- became a *sync candidate* — a row saying "this moved". What it could not do is answer the
-- provider: a pull request that changes an API still shows no verdict from this platform, because
-- there was nowhere to record one and nothing to send it with. This migration adds the two tables
-- the status adapter needs:
--
--   apiome.provider_check_runs        — the NORMALIZED check: one verdict per (binding, commit,
--                                       check name), in one of four states.
--   apiome.provider_check_deliveries  — append-only evidence of every attempt to publish one of
--                                       those verdicts to the provider.
--
-- Five rules shape the schema:
--
--   1. **Four states, provider-independent.** `pending | pass | fail | skipped`. Every provider
--      spells its own status differently — GitHub has `status` plus `conclusion`, GitLab has a
--      commit `state`, Bitbucket has a build `state` — so the *stored* vocabulary is ours and the
--      spelling is the adapter's problem (apiome-rest `app.provider_checks`). A check that has not
--      finished is `pending` and has no `completed_at`; the CHECK ties those two together so a
--      finished-looking row cannot be missing its timestamp, nor a pending one carry one.
--
--   2. **A check is identified by what it is about, not by when it ran.** `UNIQUE (binding_id,
--      commit_sha, name)` — one verdict per check name per commit of a binding. That is what makes
--      a re-run idempotent: re-running `apiome/api-change` on the same commit UPDATEs the one row
--      (bumping `attempt`) rather than fanning out a second verdict a reviewer would have to
--      reconcile. Same input, same row, same verdict.
--
--   3. **A check hangs off a binding, so it inherits the binding's authorization.** A check run
--      exists only for a draft bound to a repository ref (V264), and is removed with it. There is
--      no path to record a check against a repository this tenant has not proven it can read: the
--      binding was only written after apiome-rest performed that read through a stored credential.
--      `project_id` and `version_id` are carried rather than joined so the reviewer-facing read is
--      one index hit, and so a check still explains itself in the audit trail after the fact.
--
--   4. **Publishing is evidence, not state.** Every attempt to put a verdict on the provider
--      appends one `provider_check_deliveries` row naming the state published, the outcome, the
--      provider's status code and the provider's id for the check when it returned one. The rows
--      are append-only (trigger): a delivery ledger somebody can rewrite is not a ledger.
--      `UNIQUE (check_run_id, request_fingerprint)` is the second idempotency: publishing a verdict
--      whose normalized payload is byte-identical to one already dispatched collides instead of
--      calling the provider twice, so a webhook redelivery costs nothing at the provider either.
--
--   5. **No credential is ever stored here, and none is ever returned.** A check is published with
--      a token resolved in server memory from the linked account of the *registered repository*
--      the binding was authorized through (apiome-rest `resolve_stored_git_token`). There is
--      deliberately no token column on either table — not an encrypted one — because these rows
--      are read straight into an API model that browser clients receive. `error_message` holds a
--      provider's refusal, which is outside our control, so apiome-rest redacts it before it is
--      written (the SDK-4.2 `redact_secrets` discipline).
--
-- Rollback notes (reverse carefully in shared environments):
--   DROP TABLE IF EXISTS apiome.provider_check_deliveries;
--   DROP TABLE IF EXISTS apiome.provider_check_runs;
--   DROP FUNCTION IF EXISTS apiome.provider_check_deliveries_append_only();
--   DROP FUNCTION IF EXISTS apiome.provider_check_runs_guard_identity();

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- provider_check_runs — one normalized verdict per (binding, commit, check name).
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS provider_check_runs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Scope. Rule 3: the binding is the authorization, the rest is carried for the reads.
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    binding_id UUID NOT NULL REFERENCES draft_repository_bindings(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    version_id UUID NOT NULL REFERENCES versions(id) ON DELETE CASCADE,

    -- The provider coordinates the verdict is published against. Copied from the binding at
    -- creation so a check still names its repository once the registration is removed.
    provider VARCHAR(32) NOT NULL
        CONSTRAINT provider_check_runs_provider_check
        CHECK (provider IN ('github', 'gitlab', 'bitbucket')),
    repo_full_name VARCHAR(512) NOT NULL
        CONSTRAINT provider_check_runs_repo_full_name_check
        CHECK (length(btrim(repo_full_name)) > 0),
    -- The commit the verdict is about. A verdict always names a commit, never a branch: a branch
    -- moves, and a green check that describes bytes which are no longer there is a lie.
    commit_sha VARCHAR(64) NOT NULL
        CONSTRAINT provider_check_runs_commit_sha_check
        CHECK (length(btrim(commit_sha)) > 0),
    -- The pull request the commit belongs to, when the delivery named one. Advisory only: the
    -- verdict is attached to the commit, which is what every provider's status API addresses.
    pr_number INTEGER
        CONSTRAINT provider_check_runs_pr_number_check
        CHECK (pr_number IS NULL OR pr_number > 0),

    -- Rule 2: the check's stable name, e.g. 'apiome/api-change'. Part of the identity.
    name VARCHAR(128) NOT NULL
        CONSTRAINT provider_check_runs_name_check
        CHECK (length(btrim(name)) > 0),

    -- Rule 1: the normalized state.
    state VARCHAR(16) NOT NULL DEFAULT 'pending'
        CONSTRAINT provider_check_runs_state_check
        CHECK (state IN ('pending', 'pass', 'fail', 'skipped')),
    -- What a reviewer reads on the provider: a one-line title, a longer summary, and the link the
    -- check points back at. The link is what makes a failure a reason rather than a log.
    title VARCHAR(255) NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    details_url TEXT NOT NULL DEFAULT '',

    -- The provider's own identifier for the check, once one has been created (GitHub returns a
    -- check-run id; GitLab and Bitbucket address a status by its name/key, so this stays NULL).
    external_id VARCHAR(255),
    -- How the check came to exist, and the delivery that seeded it when a provider event did.
    origin VARCHAR(16) NOT NULL DEFAULT 'api'
        CONSTRAINT provider_check_runs_origin_check
        CHECK (origin IN ('webhook', 'api', 'sweep')),
    delivery_id VARCHAR(255),

    -- Rule 2: how many times this check has been run. A re-run resets the row to pending and
    -- increments this, so "it was re-run" is visible without a second verdict row.
    attempt INTEGER NOT NULL DEFAULT 1
        CONSTRAINT provider_check_runs_attempt_check
        CHECK (attempt >= 1),

    started_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- Rule 1: set exactly when the check leaves 'pending'.
    completed_at TIMESTAMP WITH TIME ZONE,

    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Rule 1: pending and finished are the same fact told twice; they may not disagree.
    CONSTRAINT provider_check_runs_completed_check
        CHECK ((state = 'pending') = (completed_at IS NULL))
);

-- Rule 2: one verdict per check name per commit of a binding — the re-run idempotency key.
CREATE UNIQUE INDEX IF NOT EXISTS uq_provider_check_runs_identity
    ON provider_check_runs (binding_id, commit_sha, name);

-- The reviewer-facing read: this version's checks, newest first.
CREATE INDEX IF NOT EXISTS idx_provider_check_runs_version_created
    ON provider_check_runs (version_id, created_at DESC);

-- One binding's checks, newest first — the binding panel.
CREATE INDEX IF NOT EXISTS idx_provider_check_runs_binding_created
    ON provider_check_runs (binding_id, created_at DESC);

-- "What is still running in this tenant?" and the tenant deletion path.
CREATE INDEX IF NOT EXISTS idx_provider_check_runs_tenant_pending
    ON provider_check_runs (tenant_id, created_at DESC) WHERE state = 'pending';

-- The commit read: every check on one commit of one repository, which is what a merge gate asks.
CREATE INDEX IF NOT EXISTS idx_provider_check_runs_repo_commit
    ON provider_check_runs (repo_full_name, commit_sha);

COMMENT ON TABLE provider_check_runs IS
    'One normalized API check verdict per (binding, commit, check name), in one of pending|pass|fail|skipped; the provider-independent model the status adapter publishes from (GNC-2.2, #4738)';
COMMENT ON COLUMN provider_check_runs.binding_id IS
    'The branch-to-draft binding the check belongs to; a check inherits that binding''s proven repository access and is removed with it';
COMMENT ON COLUMN provider_check_runs.provider IS 'github | gitlab | bitbucket — copied from the binding so the row stays self-describing';
COMMENT ON COLUMN provider_check_runs.commit_sha IS 'The commit the verdict is about; a verdict never names a branch, because a branch moves';
COMMENT ON COLUMN provider_check_runs.pr_number IS 'The pull request the commit belongs to, when a delivery named one; advisory — the verdict attaches to the commit';
COMMENT ON COLUMN provider_check_runs.name IS 'Stable check name, e.g. apiome/api-change; part of the identity, so a re-run updates rather than fans out';
COMMENT ON COLUMN provider_check_runs.state IS 'pending | pass | fail | skipped — the normalized vocabulary; each provider''s spelling is the adapter''s problem';
COMMENT ON COLUMN provider_check_runs.details_url IS 'The link the published check points a reviewer at, so a failure is a reason and not a log';
COMMENT ON COLUMN provider_check_runs.external_id IS 'The provider''s own id for the check (GitHub check-run id); NULL for providers that address a status by name';
COMMENT ON COLUMN provider_check_runs.origin IS 'webhook (a provider delivery seeded it) | api (an explicit call) | sweep';
COMMENT ON COLUMN provider_check_runs.attempt IS 'How many times this check has been run; a re-run resets state to pending and increments it';
COMMENT ON COLUMN provider_check_runs.completed_at IS 'When the check left pending; NULL exactly while it is pending';

-- ---------------------------------------------------------------------------------------------------
-- provider_check_deliveries — append-only evidence of every publish attempt (rule 4).
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS provider_check_deliveries (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    check_run_id UUID NOT NULL REFERENCES provider_check_runs(id) ON DELETE CASCADE,
    -- Carried rather than joined: the tenant's delivery read is one index hit, and a tenant
    -- deletion removes the rows directly.
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    provider VARCHAR(32) NOT NULL
        CONSTRAINT provider_check_deliveries_provider_check
        CHECK (provider IN ('github', 'gitlab', 'bitbucket')),
    -- The state this attempt published, which is not necessarily the check's state now.
    state VARCHAR(16) NOT NULL
        CONSTRAINT provider_check_deliveries_state_check
        CHECK (state IN ('pending', 'pass', 'fail', 'skipped')),

    -- Rule 4: sha256 over the normalized request the adapter would send. Two attempts that would
    -- send the same bytes are the same attempt.
    request_fingerprint VARCHAR(128) NOT NULL
        CONSTRAINT provider_check_deliveries_fingerprint_check
        CHECK (length(btrim(request_fingerprint)) > 0),

    -- dispatched: the provider accepted it. suppressed: nothing was sent, on purpose — checks are
    -- turned off, no credential could be resolved, or the provider has no adapter. failed: it was
    -- sent and refused.
    outcome VARCHAR(16) NOT NULL
        CONSTRAINT provider_check_deliveries_outcome_check
        CHECK (outcome IN ('dispatched', 'suppressed', 'failed')),
    -- The provider's HTTP status, when a request actually went out.
    status_code INTEGER
        CONSTRAINT provider_check_deliveries_status_code_check
        CHECK (status_code IS NULL OR (status_code BETWEEN 100 AND 599)),
    -- The provider's id for the check, when this attempt created or moved one.
    external_id VARCHAR(255),
    -- A stable reason code, and the provider's message AFTER apiome-rest redacts it. No credential
    -- is ever written here (rule 5).
    error_code VARCHAR(64),
    error_message TEXT NOT NULL DEFAULT '',

    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- A dispatch names the status it got; a suppressed attempt never reached the provider, so it
    -- cannot claim one. The V187/V197 discipline: a row may not overstate its reach.
    CONSTRAINT provider_check_deliveries_suppressed_check
        CHECK (outcome <> 'suppressed' OR (status_code IS NULL AND external_id IS NULL)),
    CONSTRAINT provider_check_deliveries_dispatched_check
        CHECK (outcome <> 'dispatched' OR status_code IS NOT NULL)
);

-- Rule 4: an identical payload is published once. A webhook redelivery costs nothing at the
-- provider, not just nothing here.
CREATE UNIQUE INDEX IF NOT EXISTS uq_provider_check_deliveries_fingerprint
    ON provider_check_deliveries (check_run_id, request_fingerprint);

-- One check's attempts, newest first.
CREATE INDEX IF NOT EXISTS idx_provider_check_deliveries_check_created
    ON provider_check_deliveries (check_run_id, created_at DESC);

-- Tenant-wide reads ("what is failing to publish?") and tenant deletion.
CREATE INDEX IF NOT EXISTS idx_provider_check_deliveries_tenant_created
    ON provider_check_deliveries (tenant_id, created_at DESC);

COMMENT ON TABLE provider_check_deliveries IS
    'Append-only record of every attempt to publish a normalized check verdict to a provider: the state sent, the outcome, the provider''s status code and id (GNC-2.2, #4738). Holds no credential.';
COMMENT ON COLUMN provider_check_deliveries.state IS 'The state this attempt published, which is not necessarily the check''s state now';
COMMENT ON COLUMN provider_check_deliveries.request_fingerprint IS
    'sha256 over the normalized provider request; the publish idempotency key, so an identical payload is never sent twice';
COMMENT ON COLUMN provider_check_deliveries.outcome IS
    'dispatched (the provider accepted it) | suppressed (nothing was sent, on purpose) | failed (sent and refused)';
COMMENT ON COLUMN provider_check_deliveries.error_message IS
    'The provider''s refusal after apiome-rest redacts it; a provider body is outside our control, so it is never written raw';

-- ---------------------------------------------------------------------------------------------------
-- Rule 2 + rule 3: what a check is about never changes.
--
-- Only the verdict and its presentation move — state, title, summary, details_url, external_id,
-- attempt, started_at, completed_at, updated_at. Which binding, which commit, which name: those
-- are the identity, and changing one would silently repoint a verdict at different bytes.
-- binding_id is exempt from nothing; project_id and version_id follow the binding and are equally
-- fixed.
-- ---------------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION apiome.provider_check_runs_guard_identity()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
       OR NEW.binding_id IS DISTINCT FROM OLD.binding_id
       OR NEW.project_id IS DISTINCT FROM OLD.project_id
       OR NEW.version_id IS DISTINCT FROM OLD.version_id
       OR NEW.provider IS DISTINCT FROM OLD.provider
       OR NEW.repo_full_name IS DISTINCT FROM OLD.repo_full_name
       OR NEW.commit_sha IS DISTINCT FROM OLD.commit_sha
       OR NEW.name IS DISTINCT FROM OLD.name
       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'provider_check_runs: what a check is about never changes — a different binding, commit or name is a different check'
            USING ERRCODE = 'check_violation';
    END IF;

    -- An attempt counter that can go backwards is not evidence of anything.
    IF NEW.attempt < OLD.attempt THEN
        RAISE EXCEPTION 'provider_check_runs: attempt never decreases'
            USING ERRCODE = 'check_violation';
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_provider_check_runs_guard_identity ON provider_check_runs;
CREATE TRIGGER trg_provider_check_runs_guard_identity
    BEFORE UPDATE ON provider_check_runs
    FOR EACH ROW
    EXECUTE FUNCTION apiome.provider_check_runs_guard_identity();

-- ---------------------------------------------------------------------------------------------------
-- Rule 4: publish attempts are evidence; they are appended to, never rewritten.
--
-- The trigger covers UPDATE only, deliberately. A BEFORE DELETE row trigger also fires for the
-- rows an ON DELETE CASCADE removes, so refusing DELETE here would make deleting a check run, a
-- binding, a project, a version or a tenant fail outright — an append-only guard that takes the
-- rest of the schema hostage. Removal is therefore governed by the cascades above (a delivery
-- outlives nothing its check run does not), and rewriting — the thing that would actually falsify
-- the ledger — is what the trigger refuses.
-- ---------------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION apiome.provider_check_deliveries_append_only()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'provider_check_deliveries is append-only: a publish attempt is evidence and cannot be rewritten'
        USING ERRCODE = 'check_violation';
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION apiome.provider_check_deliveries_append_only() IS
    'Refuses UPDATE on provider_check_deliveries (GNC-2.2). DELETE is left to the cascades, because a BEFORE DELETE guard would also block them.';

DROP TRIGGER IF EXISTS trg_provider_check_deliveries_append_only ON provider_check_deliveries;
CREATE TRIGGER trg_provider_check_deliveries_append_only
    BEFORE UPDATE ON provider_check_deliveries
    FOR EACH ROW
    EXECUTE FUNCTION apiome.provider_check_deliveries_append_only();
