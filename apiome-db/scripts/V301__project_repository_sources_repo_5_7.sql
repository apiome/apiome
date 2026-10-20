-- Multi-repository merge into one API surface (REPO-5.7, #2792).
--
-- A platform split across many repositories (one per service) is shown as one Apiome project:
-- every repository file imported into the project contributes its classes and paths, and each new
-- version carries forward what the *other* contributing files defined. Two tables record this:
--
--   * `project_repository_sources` — the project's contributing repository files, one row per
--     file lineage (repository, branch, path). `precedence` is the deterministic merge order:
--     1 is the file that contributed first, each new file takes the next number. It orders the
--     merged surface and decides which source's project-level info is kept (the first one); it
--     never resolves a conflict — two files defining the same class or path fail the import.
--     CASCADE from the project and the repository: removing either removes the contribution, and
--     the classes and paths it defined are carried forward as unattributed content.
--   * `version_entity_sources` — per-version provenance: which contributing file defined each
--     class (`entity_kind = 'class'`, keyed by class name) and each path (`'path'`, keyed by
--     pathname). Repository name, branch and path are snapshotted so the provenance still reads
--     after the source row is removed (`source_id` is then SET NULL). `carried_from_version_id`
--     is the version the entity was carried forward from, NULL when this version's import wrote
--     it. A class or path without a row was not defined by a repository (edited in Apiome, or
--     imported before REPO-5.7).
--
-- Rollback:
--   DROP TABLE IF EXISTS apiome.version_entity_sources;
--   DROP TABLE IF EXISTS apiome.project_repository_sources;
SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS apiome.project_repository_sources (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES apiome.projects(id) ON DELETE CASCADE,
    repository_id UUID NOT NULL REFERENCES apiome.tenant_repositories(id) ON DELETE CASCADE,
    branch TEXT NOT NULL CHECK (length(branch) BETWEEN 1 AND 255),
    path TEXT NOT NULL CHECK (length(path) BETWEEN 1 AND 1024),
    precedence INTEGER NOT NULL CHECK (precedence >= 1),
    first_version_id UUID REFERENCES apiome.versions(id) ON DELETE SET NULL,
    last_version_id UUID REFERENCES apiome.versions(id) ON DELETE SET NULL,
    last_blob_sha VARCHAR(64),
    created_by UUID REFERENCES apiome.users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT project_repository_sources_lineage_unique UNIQUE (project_id, repository_id, branch, path)
);

-- Precedence is not unique: two first imports racing into one project may take the same number.
-- Readers order by (precedence, created_at, id), which is still deterministic.
CREATE INDEX IF NOT EXISTS idx_project_repository_sources_project
    ON apiome.project_repository_sources (project_id, precedence, created_at, id);

CREATE INDEX IF NOT EXISTS idx_project_repository_sources_repository
    ON apiome.project_repository_sources (repository_id);

CREATE TABLE IF NOT EXISTS apiome.version_entity_sources (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    version_id UUID NOT NULL REFERENCES apiome.versions(id) ON DELETE CASCADE,
    entity_kind TEXT NOT NULL CHECK (entity_kind IN ('class', 'path')),
    entity_key TEXT NOT NULL CHECK (length(entity_key) BETWEEN 1 AND 2048),
    source_id UUID REFERENCES apiome.project_repository_sources(id) ON DELETE SET NULL,
    repository_id UUID,
    repository_full_name TEXT NOT NULL CHECK (length(repository_full_name) BETWEEN 1 AND 512),
    branch TEXT NOT NULL CHECK (length(branch) BETWEEN 1 AND 255),
    path TEXT NOT NULL CHECK (length(path) BETWEEN 1 AND 1024),
    blob_sha VARCHAR(64),
    carried_from_version_id UUID REFERENCES apiome.versions(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT version_entity_sources_entity_unique UNIQUE (version_id, entity_kind, entity_key)
);

CREATE INDEX IF NOT EXISTS idx_version_entity_sources_source
    ON apiome.version_entity_sources (source_id)
    WHERE source_id IS NOT NULL;

COMMENT ON TABLE apiome.project_repository_sources IS
    'Repository files contributing to a project''s merged API surface (REPO-5.7). One row per (repository, branch, path); precedence 1 contributed first.';
COMMENT ON COLUMN apiome.project_repository_sources.precedence IS
    'Deterministic merge order (1 = first contributor). Orders the merged surface and keeps the first source''s project info; never resolves a class/path conflict, which fails the import.';
COMMENT ON COLUMN apiome.project_repository_sources.last_version_id IS
    'The version this file was last imported into.';
COMMENT ON TABLE apiome.version_entity_sources IS
    'Per-version provenance of classes and paths in a multi-repository project (REPO-5.7). A class or path without a row was not defined by a repository.';
COMMENT ON COLUMN apiome.version_entity_sources.entity_key IS
    'Class name (entity_kind = class) or pathname (entity_kind = path).';
COMMENT ON COLUMN apiome.version_entity_sources.carried_from_version_id IS
    'Version the entity was carried forward from; NULL when this version''s import wrote it.';
