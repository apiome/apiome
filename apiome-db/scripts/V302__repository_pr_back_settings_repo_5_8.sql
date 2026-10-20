-- PR-back sync: Apiome → repository (REPO-5.8, #2793).
--
-- Changes used to flow one way only: a repository file is imported into a project. PR-back
-- renders a project version's spec and opens a pull request into the repository files the project
-- was imported from (`project_repository_sources`, V301). This table holds each repository's
-- PR-back settings — one row per registered repository:
--
--   * `project_policy` + `project_ids` — which Apiome projects may open pull requests into the
--     repository. `allow` lets only the listed projects; `deny` lets every project except the
--     listed ones. A repository without a row lets no project (PR-back is opt-in), and
--     `allow` with an empty list is the same as no row.
--   * `target_branch` — the branch pull requests merge into. NULL uses the branch the files
--     were imported from.
--   * `commit_message_template` — Mustache template for the commit message. NULL uses the
--     built-in default (`Sync {{project}} {{version}} from Apiome`).
--   * `reviewers` — GitHub logins (`octocat`) or team slugs (`acme/api-reviewers`) requested
--     as reviewers on every pull request PR-back opens.
--
-- Every pull request PR-back opens or refreshes is recorded in `apiome.access_audit`
-- (`repository.pr_back_opened` / `repository.pr_back_updated`); there is no run table.
--
-- Rollback:
--   DROP TABLE IF EXISTS apiome.repository_pr_back_settings;
SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS apiome.repository_pr_back_settings (
    repository_id UUID PRIMARY KEY REFERENCES apiome.tenant_repositories(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    project_policy TEXT NOT NULL DEFAULT 'allow' CHECK (project_policy IN ('allow', 'deny')),
    project_ids UUID[] NOT NULL DEFAULT '{}'::uuid[]
        CHECK (cardinality(project_ids) <= 500),
    target_branch TEXT CHECK (target_branch IS NULL OR length(target_branch) BETWEEN 1 AND 255),
    commit_message_template TEXT
        CHECK (commit_message_template IS NULL OR length(commit_message_template) BETWEEN 1 AND 2000),
    reviewers TEXT[] NOT NULL DEFAULT '{}'::text[]
        CHECK (cardinality(reviewers) <= 15),
    updated_by UUID REFERENCES apiome.users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_repository_pr_back_settings_tenant
    ON apiome.repository_pr_back_settings (tenant_id);

COMMENT ON TABLE apiome.repository_pr_back_settings IS
    'Per-repository PR-back settings (REPO-5.8): which projects may open pull requests into the repository, the target branch, the commit message template and the reviewers. No row = no project may PR back.';
COMMENT ON COLUMN apiome.repository_pr_back_settings.project_policy IS
    'allow = only project_ids may PR back; deny = every project except project_ids may.';
COMMENT ON COLUMN apiome.repository_pr_back_settings.target_branch IS
    'Base branch of the pull requests; NULL = the branch the files were imported from.';
COMMENT ON COLUMN apiome.repository_pr_back_settings.commit_message_template IS
    'Mustache commit message template ({{project}}, {{version}}, {{repository}}, {{branch}}, {{fileCount}}); NULL = built-in default.';
COMMENT ON COLUMN apiome.repository_pr_back_settings.reviewers IS
    'GitHub logins or org/team slugs requested as reviewers on each opened pull request.';
