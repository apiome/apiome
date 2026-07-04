-- Cross-format API identity grouping (#4410, MFI-6.4).
--
-- The same logical API imported as proto, SDL, and OpenAPI today lands as three unrelated catalog
-- items. MFI-6.4 adds a lightweight grouping so operators can manually link/unlink related artifacts
-- (and conversion provenance auto-seeds source↔converted pairs). Each project belongs to at most one
-- identity group; a group holds two or more related project ids.
--
-- Rollback notes: purely additive. To roll back:
--   DROP TABLE IF EXISTS apiome.api_identity_members;
--   DROP TABLE IF EXISTS apiome.api_identity_groups;

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- Identity groups — one row per cross-format API identity within a tenant.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS apiome.api_identity_groups (
    id          UUID         NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    tenant_id   UUID         NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    created_by  UUID         REFERENCES apiome.users(id) ON DELETE SET NULL,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE apiome.api_identity_groups IS
  'Cross-format API identity groups (#4410, MFI-6.4): a tenant-scoped grouping of related project '
  'artifacts (catalog items and publishable Projects) that represent the same logical API in '
  'different formats.';

CREATE INDEX IF NOT EXISTS idx_api_identity_groups_tenant
  ON apiome.api_identity_groups(tenant_id);

-- ---------------------------------------------------------------------------------------------------
-- Group membership — each project may belong to at most one identity group.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS apiome.api_identity_members (
    id           UUID         NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    tenant_id    UUID         NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    group_id     UUID         NOT NULL REFERENCES apiome.api_identity_groups(id) ON DELETE CASCADE,
    project_id   UUID         NOT NULL REFERENCES apiome.projects(id) ON DELETE CASCADE,
    link_source  VARCHAR(32)  NOT NULL DEFAULT 'manual',
    created_by   UUID         REFERENCES apiome.users(id) ON DELETE SET NULL,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT api_identity_members_link_source_check
        CHECK (link_source IN ('manual', 'conversion')),

    CONSTRAINT api_identity_members_project_unique
        UNIQUE (tenant_id, project_id)
);

COMMENT ON TABLE apiome.api_identity_members IS
  'Membership of a project in a cross-format API identity group (#4410, MFI-6.4). link_source records '
  'whether the link was created manually or seeded from conversion provenance (MFI-22.5).';

CREATE INDEX IF NOT EXISTS idx_api_identity_members_group
  ON apiome.api_identity_members(tenant_id, group_id);

CREATE INDEX IF NOT EXISTS idx_api_identity_members_project
  ON apiome.api_identity_members(tenant_id, project_id);
