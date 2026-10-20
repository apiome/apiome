-- Multi-repository federation: toggle and merge history (V2-REPO-8.2, #2806).
--
-- REPO-5.7 (V301) merges every repository file imported into a project into one API surface. This
-- migration adds the two things federation needs on top of it:
--
--   * `projects.repository_federation` — the project's federation switch. TRUE (the default, and
--     REPO-5.7's behaviour) merges each imported repository file with the other contributing
--     files. FALSE makes each import replace the project's surface with the importing file alone.
--   * `project_federation_merges` — the project's merge history, one row per repository-file import
--     that federation acted on:
--       - `merged`     — a multi-file merge wrote a new version;
--       - `conflicted` — two files defined the same class or path, so the import failed and wrote
--                        nothing; `conflicts` holds each one with every source's definition;
--       - `replaced`   — federation was off and the import dropped content other files defined.
--     The repository name, branch and path are snapshotted so the history still reads after the
--     repository or the version is removed.
--
-- Rows are written by apiome-rest together with their `apiome.access_audit` row
-- (`repository.federation_merged` / `…_conflicted` / `…_replaced`) in one transaction.
--
-- Rollback:
--   DROP TABLE IF EXISTS apiome.project_federation_merges;
--   ALTER TABLE apiome.projects DROP COLUMN IF EXISTS repository_federation;
SET search_path TO apiome, public;

ALTER TABLE apiome.projects
    ADD COLUMN IF NOT EXISTS repository_federation BOOLEAN NOT NULL DEFAULT TRUE;

CREATE TABLE IF NOT EXISTS apiome.project_federation_merges (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES apiome.projects(id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ('merged', 'conflicted', 'replaced')),
    version_id UUID REFERENCES apiome.versions(id) ON DELETE SET NULL,
    parent_version_id UUID REFERENCES apiome.versions(id) ON DELETE SET NULL,
    repository_id UUID REFERENCES apiome.tenant_repositories(id) ON DELETE SET NULL,
    repository_full_name TEXT NOT NULL CHECK (length(repository_full_name) BETWEEN 1 AND 512),
    branch TEXT NOT NULL CHECK (length(branch) BETWEEN 1 AND 255),
    path TEXT NOT NULL CHECK (length(path) BETWEEN 1 AND 1024),
    source_count INTEGER NOT NULL DEFAULT 1 CHECK (source_count >= 0),
    classes_carried INTEGER NOT NULL DEFAULT 0 CHECK (classes_carried >= 0),
    paths_carried INTEGER NOT NULL DEFAULT 0 CHECK (paths_carried >= 0),
    removed_count INTEGER NOT NULL DEFAULT 0 CHECK (removed_count >= 0),
    conflict_count INTEGER NOT NULL DEFAULT 0 CHECK (conflict_count >= 0),
    sources JSONB NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(sources) = 'array'),
    conflicts JSONB NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(conflicts) = 'array'),
    actor_id UUID REFERENCES apiome.users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- A conflicted import wrote no version.
    CONSTRAINT project_federation_merges_conflict_no_version
        CHECK (status <> 'conflicted' OR version_id IS NULL)
);

CREATE INDEX IF NOT EXISTS idx_project_federation_merges_project
    ON apiome.project_federation_merges (project_id, created_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_project_federation_merges_repository
    ON apiome.project_federation_merges (repository_id, created_at DESC, id DESC)
    WHERE repository_id IS NOT NULL;

COMMENT ON COLUMN apiome.projects.repository_federation IS
    'Multi-repository federation (V2-REPO-8.2): TRUE merges each imported repository file with the other contributing files (REPO-5.7); FALSE makes each import replace the surface with the importing file alone.';
COMMENT ON TABLE apiome.project_federation_merges IS
    'Merge history of a federated project (V2-REPO-8.2): one row per repository-file import federation acted on — merged, conflicted (nothing written; per-source definitions in conflicts) or replaced (federation off).';
COMMENT ON COLUMN apiome.project_federation_merges.conflicts IS
    'For a conflicted import: [{kind, key, sources: [{role, repositoryFullName, branch, path, definition}]}], one entry per colliding class or path.';
COMMENT ON COLUMN apiome.project_federation_merges.sources IS
    'The contributing files of the merge in precedence order: [{repositoryFullName, branch, path, precedence}].';
