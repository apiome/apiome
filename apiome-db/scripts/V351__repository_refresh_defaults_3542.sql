-- Workspace refresh defaults for repositories (RAR-6.5, #3542).
--
-- Every repository carries three refresh settings: its cadence (RAR-3.1
-- `refresh_interval_seconds`), its conflict policy (RAR-4.5 `refresh_conflict_policy`) and its
-- auto-refresh switch (RAR-3.3 `auto_refresh_enabled`). Until now each new repository started
-- from the built-in values (300 s, hold-for-review, on) and an organisation that wanted
-- something else had to change every repository by hand — and the repositories drifted apart.
--
-- This migration adds a workspace-level preset and lets each repository follow it per setting:
--
--   workspace defaults { interval: 900 s, conflict: overwrite, auto-refresh: on }
--      └─ a new repository starts from them ──► each setting can be overridden on the repository
--
--   1. `apiome.tenant_repository_refresh_defaults` — one row per workspace. No row means the
--      built-in values. A new repository is created with the row's values (the insert reads
--      them in the same statement, so a repository can never miss them).
--
--   2. Three `inherits_*` flags on `tenant_repositories`, one per setting. TRUE means the
--      setting follows the workspace default: changing the defaults with "apply to repositories
--      that follow them" rewrites exactly those settings. Changing a setting on the repository
--      sets its flag to FALSE (an override); "Use workspace default" copies the default back and
--      sets it to TRUE again. Per setting rather than per repository, so a repository that only
--      turned auto-refresh off still follows the workspace cadence and conflict policy.
--
-- Backfill: an existing repository is treated as following a default only where its value is
-- still the built-in one. A repository someone already changed keeps its value as an override,
-- so introducing workspace defaults never silently rewrites a deliberate choice.
SET search_path TO apiome, public;

-- ─── 1. The workspace preset ──────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS apiome.tenant_repository_refresh_defaults (
    tenant_id                UUID PRIMARY KEY REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    refresh_interval_seconds INT NOT NULL DEFAULT 300 CHECK (refresh_interval_seconds > 0),
    refresh_conflict_policy  VARCHAR(32) NOT NULL DEFAULT 'hold-for-review'
                             CHECK (refresh_conflict_policy IN ('overwrite', 'hold-for-review', 'new-branch')),
    auto_refresh_enabled     BOOLEAN NOT NULL DEFAULT TRUE,
    -- Who last changed the defaults, for the audit answer to "why did every repository change".
    updated_by               UUID REFERENCES apiome.users(id) ON DELETE SET NULL,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE apiome.tenant_repository_refresh_defaults IS
    'Workspace refresh defaults for repositories (RAR-6.5, #3542): the cadence, conflict policy and auto-refresh switch a new repository starts from, and that repositories following them are re-aligned to when the defaults change. No row means the built-in values (300 s, hold-for-review, on).';

-- ─── 2. Per-setting inheritance ───────────────────────────────────────────────

ALTER TABLE apiome.tenant_repositories
  ADD COLUMN IF NOT EXISTS inherits_refresh_interval BOOLEAN NOT NULL DEFAULT TRUE,
  ADD COLUMN IF NOT EXISTS inherits_conflict_policy  BOOLEAN NOT NULL DEFAULT TRUE,
  ADD COLUMN IF NOT EXISTS inherits_auto_refresh     BOOLEAN NOT NULL DEFAULT TRUE;

COMMENT ON COLUMN apiome.tenant_repositories.inherits_refresh_interval IS
    'TRUE: refresh_interval_seconds follows the workspace default (RAR-6.5) and is rewritten when the defaults are re-applied. FALSE: the repository overrides it.';
COMMENT ON COLUMN apiome.tenant_repositories.inherits_conflict_policy IS
    'TRUE: refresh_conflict_policy follows the workspace default (RAR-6.5). FALSE: the repository overrides it. Per-file overrides (repository_conflict_policy_override) are unaffected.';
COMMENT ON COLUMN apiome.tenant_repositories.inherits_auto_refresh IS
    'TRUE: auto_refresh_enabled follows the workspace default (RAR-6.5). FALSE: the repository overrides it.';

-- Existing repositories follow a default only where they still hold the built-in value.
UPDATE apiome.tenant_repositories
SET inherits_refresh_interval = (refresh_interval_seconds = 300),
    inherits_conflict_policy  = (refresh_conflict_policy = 'hold-for-review'),
    inherits_auto_refresh     = (auto_refresh_enabled = TRUE);
