-- Standing sources of a provider contract — PFX-8.7 (#7304).
--
-- A provider no longer has to remember to publish its provider contract for every version. A
-- provider pacticipant may name, once, where its contract comes from:
--
--   * `on_project_publish` — each time a version of the project the pacticipant is bound to
--     (`pacticipant.project_id`, V432) is published, that version is rendered and published as
--     the provider contract of provider version `<version label>`. Drafts are never published.
--   * `repository_id` + `repository_path` + `repository_branch` — on every push to that branch of
--     a registered repository, the file at that path is published with the pushed commit as the
--     provider version.
--
-- One row per pacticipant; a pacticipant without one has no standing source. Turning a source off
-- (or deleting the row) stops new publishes only: contracts already published stay. Every
-- automatic publish is written to `access_audit` by apiome-rest, with its outcome and reason.
--
-- Tenancy: both references are composite `(id, tenant_id)` keys, so a row can only name a
-- pacticipant and a repository of its own workspace. Deleting the repository clears the
-- repository source only (`SET NULL (repository_id)`); the check then turns the path and branch
-- off with it, so the source is never half-set.
--
-- Online: a new, empty table.
--
-- Rollback notes (reverse carefully in shared environments):
--   DROP TABLE IF EXISTS apiome.provider_contract_source;

SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS provider_contract_source (
    pacticipant_id UUID NOT NULL,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    -- Publish each published version of the bound project as the provider contract.
    on_project_publish BOOLEAN NOT NULL DEFAULT FALSE,

    -- Publish this file on every push to this branch, the commit being the provider version.
    repository_id UUID,
    repository_path TEXT
        CONSTRAINT provider_contract_source_path_check
            CHECK (repository_path IS NULL
                   OR (btrim(repository_path) <> '' AND length(repository_path) <= 1024)),
    repository_branch VARCHAR(255)
        CONSTRAINT provider_contract_source_branch_check
            CHECK (repository_branch IS NULL OR btrim(repository_branch) <> ''),

    updated_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- The repository source is all or nothing — but a deleted repository nulls only its id, so a
    -- path or branch without a repository is allowed and simply never fires.
    CONSTRAINT provider_contract_source_repository_check
        CHECK (repository_id IS NULL OR (repository_path IS NOT NULL AND repository_branch IS NOT NULL)),

    -- Led by the pacticipant's composite key, so it also serves that foreign key's check.
    CONSTRAINT provider_contract_source_pkey PRIMARY KEY (pacticipant_id, tenant_id),
    CONSTRAINT provider_contract_source_pacticipant_fk
        FOREIGN KEY (pacticipant_id, tenant_id)
        REFERENCES pacticipant (id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT provider_contract_source_repository_fk
        FOREIGN KEY (repository_id, tenant_id)
        REFERENCES tenant_repositories (id, tenant_id) ON DELETE SET NULL (repository_id)
);

-- "Which providers follow a file of this repository" (every push) and the repository FK check.
CREATE INDEX IF NOT EXISTS idx_provider_contract_source_repository
    ON provider_contract_source (repository_id, tenant_id)
    WHERE repository_id IS NOT NULL;
-- The workspace FK check (and a workspace delete).
CREATE INDEX IF NOT EXISTS idx_provider_contract_source_tenant
    ON provider_contract_source (tenant_id);
CREATE INDEX IF NOT EXISTS idx_provider_contract_source_updated_by
    ON provider_contract_source (updated_by)
    WHERE updated_by IS NOT NULL;

COMMENT ON TABLE provider_contract_source IS
    'Where a provider pacticipant''s contract is published from automatically (PFX-8.7, #7304)';
COMMENT ON COLUMN provider_contract_source.on_project_publish IS
    'Publish each published version of the bound project as the provider contract (provider version = version label); drafts never';
COMMENT ON COLUMN provider_contract_source.repository_id IS
    'Registered repository whose pushes publish repository_path; cleared when the repository is deleted';
COMMENT ON COLUMN provider_contract_source.repository_path IS
    'Repository-relative path of the OpenAPI or AsyncAPI document published on every push';
COMMENT ON COLUMN provider_contract_source.repository_branch IS
    'The branch whose pushes publish the file; the pushed commit is the provider version';
