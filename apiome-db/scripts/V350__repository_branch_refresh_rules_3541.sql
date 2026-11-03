-- Per-branch repository refresh policy (RAR-6.4, #3541).
--
-- A repository often tracks several branches — `main` plus release branches, a sandbox —
-- and each one stands for a different line of the API. Until now the refresh settings were
-- repository-wide (RAR-3.1 cadence, RAR-3.3 opt-out), so every tracked branch refreshed on
-- the same schedule and nothing said which line of versions a branch's refresh belongs to.
-- This migration lets a repository carry per-branch rules:
--
--   branch main      → version line "latest"   refresh on,  every 5 minutes
--   branch release/* → version line "2.x"      refresh on,  every hour
--   branch sandbox   →                          refresh off
--
-- Three pieces:
--
--   1. `apiome.repository_branch_refresh_rule` — the rules. A rule names a branch exactly
--      (`main`) or with a glob (`release/*`); when several match, the application picks the
--      most specific (an exact name over any glob, then the glob with the most literal
--      characters), in `app/repository_branch_refresh_policy.py`. A branch no rule matches
--      keeps the repository-wide settings, so a repository with no rules behaves exactly as
--      before. Rules are configuration and live in their own table, like the RAR-4.5
--      conflict-policy overrides, because the file index is rewritten by every scan.
--
--   2. `apiome.repository_branch_refresh_state` — when each branch was last refreshed. A
--      glob rule covers many branches, so a per-branch cadence cannot be measured from one
--      repository-wide `last_refreshed_at`: the sweep stamps one row per branch it refreshes
--      and measures each branch's interval from its own row.
--
--   3. `tenant_repository_refresh_jobs.target_version_line` — the version line of the rule
--      that matched the job's branch, snapshotted at enqueue time like the rest of the job
--      (RAR-3.2), so the executor names the refreshed version from it even if the rule
--      changes later. NULL when no rule (or a rule without a line) matched.
--
-- The repository-wide `auto_refresh_enabled` stays the master switch: when it is off, no
-- branch refreshes, whatever its rule says.
SET search_path TO apiome, public;

-- ─── 1. Branch rules ──────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS apiome.repository_branch_refresh_rule (
    id                       UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id                UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    repository_id            UUID NOT NULL REFERENCES apiome.tenant_repositories(id) ON DELETE CASCADE,
    -- An exact branch name (`main`) or a glob (`release/*`, `feature/**`).
    branch_pattern           TEXT NOT NULL CHECK (length(btrim(branch_pattern)) > 0),
    refresh_enabled          BOOLEAN NOT NULL DEFAULT TRUE,
    -- NULL inherits the repository's refresh_interval_seconds; the sweep clamps either to
    -- the global floor, so a rule cannot defeat it.
    refresh_interval_seconds INT CHECK (refresh_interval_seconds IS NULL OR refresh_interval_seconds > 0),
    -- The version line a refresh of a matching branch lands in (`latest`, `2.x`); NULL keeps
    -- the refresh's default naming.
    target_version_line      VARCHAR(64)
                             CHECK (target_version_line IS NULL OR target_version_line ~ '^[A-Za-z0-9][A-Za-z0-9._-]*$'),
    created_by               UUID REFERENCES apiome.users(id) ON DELETE SET NULL,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_repository_branch_refresh_rule_pattern UNIQUE (repository_id, branch_pattern)
);

COMMENT ON TABLE apiome.repository_branch_refresh_rule IS
    'Per-branch refresh rules for a Git repository (RAR-6.4, #3541). A rule names a branch exactly or by glob; the most specific match wins; a branch no rule matches keeps the repository-wide refresh settings. The repository''s auto_refresh_enabled remains the master switch.';
COMMENT ON COLUMN apiome.repository_branch_refresh_rule.branch_pattern IS
    'An exact branch name (main) or a glob (release/*). Unique per repository.';
COMMENT ON COLUMN apiome.repository_branch_refresh_rule.refresh_enabled IS
    'FALSE stops matching branches from refreshing on the schedule or on push; a manual Refresh now still runs.';
COMMENT ON COLUMN apiome.repository_branch_refresh_rule.refresh_interval_seconds IS
    'Cadence for matching branches; NULL inherits tenant_repositories.refresh_interval_seconds. Clamped up to the global floor at sweep time.';
COMMENT ON COLUMN apiome.repository_branch_refresh_rule.target_version_line IS
    'Version line a refresh of a matching branch lands in: the refreshed version is labelled <line>-<UTC timestamp> and parented on the latest version of that line. NULL keeps the default naming.';

CREATE INDEX IF NOT EXISTS idx_repository_branch_refresh_rule_tenant_repo
    ON apiome.repository_branch_refresh_rule (tenant_id, repository_id);

-- ─── 2. Per-branch refresh anchor ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS apiome.repository_branch_refresh_state (
    repository_id     UUID NOT NULL REFERENCES apiome.tenant_repositories(id) ON DELETE CASCADE,
    branch            TEXT NOT NULL,
    last_refreshed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (repository_id, branch)
);

COMMENT ON TABLE apiome.repository_branch_refresh_state IS
    'When the sweep last refreshed each branch of a repository (RAR-6.4, #3541), so each branch''s cadence is measured from its own refresh rather than the repository-wide last_refreshed_at.';

-- ─── 3. The version line a job lands in ───────────────────────────────────────

ALTER TABLE apiome.tenant_repository_refresh_jobs
  ADD COLUMN IF NOT EXISTS target_version_line VARCHAR(64);

COMMENT ON COLUMN apiome.tenant_repository_refresh_jobs.target_version_line IS
    'Version line of the branch rule that matched this job''s branch at enqueue time (RAR-6.4); the executor labels the refreshed version <line>-<UTC timestamp>. NULL when no rule set a line.';
