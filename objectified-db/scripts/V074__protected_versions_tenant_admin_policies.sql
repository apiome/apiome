-- Protected versions: tenant-admin policies on tags, branches, and revisions (#504)
SET search_path TO odb, public;

ALTER TABLE version_tags
  ADD COLUMN IF NOT EXISTS protected BOOLEAN NOT NULL DEFAULT false;

COMMENT ON COLUMN version_tags.protected IS 'When true, only tenant admins may move/delete this tag or clear protection (Git-like tag protection)';

ALTER TABLE version_branches
  ADD COLUMN IF NOT EXISTS protected BOOLEAN NOT NULL DEFAULT false;

COMMENT ON COLUMN version_branches.protected IS 'When true, only tenant admins may delete this branch (Git-like branch protection)';

ALTER TABLE versions
  ADD COLUMN IF NOT EXISTS revision_locked BOOLEAN NOT NULL DEFAULT false;

COMMENT ON COLUMN versions.revision_locked IS 'When true, only tenant admins may soft-delete this revision (locked baseline)';

CREATE TABLE IF NOT EXISTS version_protection_audit (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    project_id UUID REFERENCES projects(id) ON DELETE SET NULL,
    actor_id UUID REFERENCES users(id) ON DELETE SET NULL,
    action VARCHAR(96) NOT NULL,
    resource_type VARCHAR(32) NOT NULL,
    resource_id UUID NOT NULL,
    outcome VARCHAR(24) NOT NULL,
    detail JSONB,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_version_protection_audit_tenant_created
  ON version_protection_audit(tenant_id, created_at DESC);

COMMENT ON TABLE version_protection_audit IS 'Audit trail for version protection policy changes and admin overrides';
