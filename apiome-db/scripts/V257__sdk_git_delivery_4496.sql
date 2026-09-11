-- Git delivery (PR mode) — SDK-4.2 (#4496).
--
-- Registry publishing (SDK-4.1, V256) serves an SDK's *consumers*. Git delivery serves its
-- *owners*: the regenerated SDK arrives as a pull request against the tenant's own repository,
-- where their normal review and CI apply. Doing that on a tenant's behalf needs two durable things
-- no existing table holds — where each SDK goes, and the record of every attempt to send it there.
--
--   sdk_git_delivery_targets — one project's delivery destination for one ecosystem.
--   sdk_git_delivery_runs    — every delivery attempt, what it wrote, and what GitHub said.
--
-- Five rules shape the schema:
--
--   1. **No new credential store.** A target names a registered repository
--      (`tenant_repositories`), and a delivery authenticates with that repository's *existing*
--      linked-account integration (`linked_account_id` + `created_by` → `external_auth_providers`).
--      There is deliberately no token column anywhere in this migration: the ticket's acceptance
--      criterion is "works with the existing repository OAuth integrations (no new credential
--      type)", and a schema with nowhere to put a token is how that stays true.
--
--   2. **One destination per project per ecosystem.** A project's npm SDK goes to exactly one
--      repository path, so a delivery never has to choose. Several projects — or one project's npm
--      and PyPI SDKs — may share a repository; the application keeps their branches apart by naming
--      each after its project and ecosystem as well as its version.
--
--   3. **The target path is stored normalised.** Relative, no leading or trailing `/`, no `..`, no
--      `.git` segment, the empty string meaning the repository root. The CHECKs repeat the
--      application's rule so a hand-edited row cannot aim a delivery outside the repository or into
--      its `.git` directory.
--
--   4. **Failures are runs, not missing rows.** A run is inserted `in_progress` before anything is
--      written to GitHub and closed with its outcome — `opened`, `updated`, `unchanged`,
--      `up_to_date` or `failed` with an `error_code` and a redacted `log`. The ticket's criterion
--      "credential failures and push rejections surface as failed jobs with actionable logs" is
--      this column set. No version number is *claimed* here (unlike `sdk_publish_runs`): a pull
--      request is not a release, so the regen counter is read from the publish ledger, never
--      allocated by this one.
--
--   5. **A run outlives its version, its target and its repository, but not its project.**
--      `version_id`, `target_id` and `repository_id` are `ON DELETE SET NULL`, and the coordinates
--      that matter — the repository's full name, the branch, the commit, the pull request — are
--      copied onto the run, so the record that PR #42 was opened from revision X survives any of
--      them being deleted. `project_id` and `tenant_id` cascade.
--
-- **No new RBAC resource.** Configuring where a project's SDK goes is `projects:edit`; delivering
-- one is `versions:publish`, exactly as publishing to a registry is. Adding a resource costs four
-- synchronised edits (the role grid, the REST `Resource` enum, the enforcement call sites, and the
-- UI role matrix), and a permission that would always be granted alongside an existing one earns
-- none of them — the argument V254 (CTG-4.5), V255 (SDK-3.4) and V256 (SDK-4.1) made.
--
-- Rollback notes (reverse carefully in shared environments):
--   DROP TABLE IF EXISTS apiome.sdk_git_delivery_runs;
--   DROP TABLE IF EXISTS apiome.sdk_git_delivery_targets;

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- sdk_git_delivery_targets — where one project's SDK for one ecosystem is delivered.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sdk_git_delivery_targets (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,

    -- The SDK-4.1 packaging layouts a delivery can commit. `gomod` is absent for the same reason it
    -- is absent from V256: there is no SDK-4.1 layout for it.
    ecosystem VARCHAR(16) NOT NULL
        CONSTRAINT sdk_git_delivery_targets_ecosystem_check
            CHECK (ecosystem IN ('npm', 'pypi')),

    -- Rule 1: the destination *and* the credential, in one reference. Cascades: a target pointing
    -- at a repository that no longer exists is configuration nothing can ever use.
    repository_id UUID NOT NULL REFERENCES tenant_repositories(id) ON DELETE CASCADE,

    -- The branch the pull request targets. NULL means "the repository's default branch, as GitHub
    -- reports it at delivery time" — a stored copy of the default would go stale on a rename.
    base_branch VARCHAR(255)
        CONSTRAINT sdk_git_delivery_targets_base_branch_check
            CHECK (base_branch IS NULL OR (base_branch <> '' AND base_branch !~ '[[:space:]~^:?*\[\\]')),

    -- Rule 3: relative, normalised, '' for the repository root.
    target_path TEXT NOT NULL DEFAULT ''
        CONSTRAINT sdk_git_delivery_targets_path_check
            CHECK (
                target_path !~ '^/'
                AND target_path !~ '/$'
                AND target_path !~ '(^|/)\.\.?(/|$)'
                AND target_path !~ '(^|/)\.git(/|$)'
                AND target_path !~ '//'
                AND target_path !~ '\\'
            ),

    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    updated_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Rule 2, enforced.
CREATE UNIQUE INDEX IF NOT EXISTS idx_sdk_git_delivery_targets_project
    ON sdk_git_delivery_targets (tenant_id, project_id, ecosystem);

-- "Which projects deliver into this repository?" — asked when a repository is removed.
CREATE INDEX IF NOT EXISTS idx_sdk_git_delivery_targets_repository
    ON sdk_git_delivery_targets (repository_id);

COMMENT ON TABLE sdk_git_delivery_targets IS
    'SDK-4.2 (#4496): where one project''s SDK for one ecosystem is delivered as a pull request — '
    'a registered repository, a base branch and a path inside it. Authenticates with the '
    'repository''s existing linked-account integration; there is no token column.';

COMMENT ON COLUMN sdk_git_delivery_targets.base_branch IS
    'The pull request''s base. NULL means the repository''s default branch as GitHub reports it at '
    'delivery time.';

COMMENT ON COLUMN sdk_git_delivery_targets.target_path IS
    'Repository-relative directory the SDK is committed under, normalised (no leading or trailing '
    'slash, no .. or .git segment). The empty string is the repository root.';

-- ---------------------------------------------------------------------------------------------------
-- sdk_git_delivery_runs — one row per delivery attempt.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sdk_git_delivery_runs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,

    -- Rule 5: provenance that survives what it points at.
    version_id UUID REFERENCES versions(id) ON DELETE SET NULL,
    target_id UUID REFERENCES sdk_git_delivery_targets(id) ON DELETE SET NULL,
    repository_id UUID REFERENCES tenant_repositories(id) ON DELETE SET NULL,

    ecosystem VARCHAR(16) NOT NULL
        CONSTRAINT sdk_git_delivery_runs_ecosystem_check CHECK (ecosystem IN ('npm', 'pypi')),

    -- Rule 4. `in_progress` while GitHub is being written to; `opened` created a pull request;
    -- `updated` pushed a new commit to (or refreshed) the open one; `unchanged` found the open pull
    -- request already carrying exactly this SDK and wrote nothing; `up_to_date` found the base
    -- branch already containing it, so no pull request was needed; `failed` says why in
    -- `error_code` and `log`.
    status VARCHAR(24) NOT NULL
        CONSTRAINT sdk_git_delivery_runs_status_check
            CHECK (status IN ('in_progress', 'opened', 'updated', 'unchanged', 'up_to_date', 'failed')),

    -- The version the committed package carries, recorded so it is auditable. Nullable: a run that
    -- failed before the version line could be mapped still records that it failed.
    version_line TEXT,
    release_series VARCHAR(64),
    regen_counter INTEGER
        CONSTRAINT sdk_git_delivery_runs_counter_check CHECK (regen_counter IS NULL OR regen_counter >= 0),
    package_name TEXT,
    package_version VARCHAR(128),

    -- Where it went, copied from the target and the repository at delivery time (rule 5).
    repository_full_name VARCHAR(512),
    base_branch VARCHAR(255),
    target_path TEXT,
    branch_name VARCHAR(255),

    -- What was written. SHA-1 object ids are 40 hex characters; 64 leaves room for SHA-256
    -- repositories.
    base_sha VARCHAR(64),
    commit_sha VARCHAR(64),
    pull_request_number INTEGER
        CONSTRAINT sdk_git_delivery_runs_pr_number_check
            CHECK (pull_request_number IS NULL OR pull_request_number > 0),
    pull_request_url TEXT,

    -- The changed-files overview the pull request body carries: counts plus a capped path list.
    changes JSONB NOT NULL DEFAULT '{}'::jsonb
        CONSTRAINT sdk_git_delivery_runs_changes_object_check
            CHECK (jsonb_typeof(changes) = 'object'),

    -- The provenance embedded in the committed package's own metadata, verbatim.
    provenance JSONB NOT NULL DEFAULT '{}'::jsonb
        CONSTRAINT sdk_git_delivery_runs_provenance_object_check
            CHECK (jsonb_typeof(provenance) = 'object'),

    -- The step-by-step log, capped by the application and written through the secret redactor, so
    -- a GitHub error quoting the token it rejected cannot land here.
    log JSONB NOT NULL DEFAULT '[]'::jsonb
        CONSTRAINT sdk_git_delivery_runs_log_array_check CHECK (jsonb_typeof(log) = 'array'),

    error_code VARCHAR(64),
    error_message TEXT,

    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMPTZ,
    created_by UUID REFERENCES users(id) ON DELETE SET NULL
);

-- Listing a project's delivery history, newest first.
CREATE INDEX IF NOT EXISTS idx_sdk_git_delivery_runs_history
    ON sdk_git_delivery_runs (tenant_id, project_id, started_at DESC);

-- "What happened to this branch?" — the pull request a run updated is found by its branch.
CREATE INDEX IF NOT EXISTS idx_sdk_git_delivery_runs_branch
    ON sdk_git_delivery_runs (tenant_id, project_id, ecosystem, branch_name);

COMMENT ON TABLE sdk_git_delivery_runs IS
    'SDK-4.2 (#4496): one row per git delivery attempt — the branch, commit and pull request it '
    'wrote, the changed-files overview, the embedded provenance, and a redacted event log. A failed '
    'run is kept with its error code so a credential failure or a push rejection is a record, not '
    'an absence.';

COMMENT ON COLUMN sdk_git_delivery_runs.status IS
    'in_progress while GitHub is being written to; opened created a pull request; updated pushed to '
    'or refreshed the open one; unchanged wrote nothing because the open pull request already '
    'carries this SDK; up_to_date wrote nothing because the base branch already contains it; failed '
    'names its reason in error_code.';

COMMENT ON COLUMN sdk_git_delivery_runs.log IS
    'Ordered delivery events, each {at, step, level, message}. Written through the secret redactor: '
    'a provider error quoting the repository token is replaced before it is stored.';
