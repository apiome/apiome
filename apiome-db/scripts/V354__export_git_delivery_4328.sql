-- Export git delivery runs — MFX-38.1 (#4328).
--
-- An export job (MFX-4.x) ends with a download. Git delivery sends the same bundle where specs
-- actually live: a branch of the consumer's repository with a pull request (or a commit straight to
-- a branch), its description carrying the export's fidelity summary. This table is the record of
-- every attempt — what it wrote, where, and what the provider said.
--
-- Five rules shape it (the SDK-4.2 git delivery ledger, V257, made the same choices):
--
--   1. **No new credential store.** A run names a registered repository (`tenant_repositories`),
--      and the delivery authenticates with that repository's *existing* linked-account integration.
--      There is no token column.
--
--   2. **Configuration rides on the request, not in a table.** Where an export goes — repository,
--      path, base branch, pull request or direct commit — is given with each delivery; MFX-38.4
--      (#4331) adds saved delivery profiles. Each run copies what it was asked so the record stands
--      on its own.
--
--   3. **The target path is stored normalised.** Relative, no leading or trailing `/`, no `..`, no
--      `.git` segment, '' for the repository root — the CHECK repeats the application's rule.
--
--   4. **Failures are runs, not missing rows.** A run is inserted `in_progress` before anything is
--      written to the provider and closed with its outcome: `opened`, `updated`, `unchanged`,
--      `up_to_date`, `committed` (direct-commit mode) or `failed` with an `error_code` and a redacted
--      `log`.
--
--   5. **A run outlives its repository, but not its tenant.** `repository_id` is `ON DELETE SET
--      NULL` and the coordinates that matter — full name, branch, commit, pull request — are copied
--      onto the run. The exported artifact can be a project or a catalog item, so `artifact_id` has
--      no foreign key; the export job itself lives in the shared job store, keyed by `job_id`.
--
-- **No new RBAC resource.** Delivering an export into a repository is `versions:publish`, exactly as
-- opening a PR-back pull request (REPO-5.8) or an SDK delivery (SDK-4.2) is.
--
-- Rollback notes (reverse carefully in shared environments):
--   DROP TABLE IF EXISTS apiome.export_git_delivery_runs;

SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS export_git_delivery_runs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    -- Rule 5: what was exported, without foreign keys that would make the record disappear.
    job_id VARCHAR(64) NOT NULL,
    artifact_id VARCHAR(64) NOT NULL,
    version_record_id VARCHAR(64),
    version_label TEXT,
    export_target VARCHAR(128),

    repository_id UUID REFERENCES tenant_repositories(id) ON DELETE SET NULL,

    -- `pr`: a delivery branch and one pull request it keeps up to date. `commit`: a commit straight
    -- onto the base branch, fast-forward only.
    mode VARCHAR(16) NOT NULL
        CONSTRAINT export_git_delivery_runs_mode_check CHECK (mode IN ('pr', 'commit')),

    -- Rule 4.
    status VARCHAR(24) NOT NULL
        CONSTRAINT export_git_delivery_runs_status_check
            CHECK (status IN ('in_progress', 'opened', 'updated', 'unchanged', 'up_to_date',
                              'committed', 'failed')),

    repository_full_name VARCHAR(512),
    base_branch VARCHAR(255),
    -- Rule 3: relative, normalised, '' for the repository root.
    target_path TEXT NOT NULL DEFAULT ''
        CONSTRAINT export_git_delivery_runs_path_check
            CHECK (
                target_path !~ '^/'
                AND target_path !~ '/$'
                AND target_path !~ '(^|/)\.\.?(/|$)'
                AND target_path !~ '(^|/)\.git(/|$)'
                AND target_path !~ '//'
                AND target_path !~ '\\'
            ),
    branch_name VARCHAR(255),

    base_sha VARCHAR(64),
    commit_sha VARCHAR(64),
    pull_request_number INTEGER
        CONSTRAINT export_git_delivery_runs_pr_number_check
            CHECK (pull_request_number IS NULL OR pull_request_number > 0),
    pull_request_url TEXT,

    -- The changed-files overview: counts plus a capped path list.
    changes JSONB NOT NULL DEFAULT '{}'::jsonb
        CONSTRAINT export_git_delivery_runs_changes_object_check CHECK (jsonb_typeof(changes) = 'object'),

    -- The export's fidelity summary (tier, preserved share, counts) as the pull request carried it.
    fidelity JSONB NOT NULL DEFAULT '{}'::jsonb
        CONSTRAINT export_git_delivery_runs_fidelity_object_check CHECK (jsonb_typeof(fidelity) = 'object'),

    -- The step-by-step log, written through the secret redactor.
    log JSONB NOT NULL DEFAULT '[]'::jsonb
        CONSTRAINT export_git_delivery_runs_log_array_check CHECK (jsonb_typeof(log) = 'array'),

    error_code VARCHAR(64),
    error_message TEXT,

    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMPTZ,
    created_by UUID REFERENCES users(id) ON DELETE SET NULL
);

-- A job's deliveries, newest first.
CREATE INDEX IF NOT EXISTS idx_export_git_delivery_runs_job
    ON export_git_delivery_runs (tenant_id, job_id, started_at DESC);

-- An artifact's delivery history, newest first (and what MFX-38.4's audit view reads).
CREATE INDEX IF NOT EXISTS idx_export_git_delivery_runs_artifact
    ON export_git_delivery_runs (tenant_id, artifact_id, started_at DESC);

COMMENT ON TABLE export_git_delivery_runs IS
    'MFX-38.1 (#4328): one row per export git delivery — the branch, commit and pull request (or '
    'direct commit) it wrote, the changed-files overview, the fidelity summary the pull request '
    'carried, and a redacted event log. A failed run is kept with its error code.';

COMMENT ON COLUMN export_git_delivery_runs.status IS
    'in_progress while the provider is being written to; opened created a pull request; updated '
    'pushed to or refreshed the open one; unchanged wrote nothing because the open pull request '
    'already carries this export; up_to_date wrote nothing because the base branch already holds it; '
    'committed fast-forwarded the base branch (direct-commit mode); failed names its reason in '
    'error_code.';

COMMENT ON COLUMN export_git_delivery_runs.log IS
    'Ordered delivery events, each {at, step, level, message}. Written through the secret redactor: '
    'a provider error quoting the repository token is replaced before it is stored.';
