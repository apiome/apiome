-- Workflow audit ledger for git-like version actions (#2577, P1-05)
SET search_path TO odb, public;

CREATE TABLE IF NOT EXISTS workflow_audit (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    project_id UUID,
    version_id UUID,
    action VARCHAR(96) NOT NULL,
    outcome VARCHAR(24) NOT NULL,
    actor_id UUID REFERENCES users(id) ON DELETE SET NULL,
    detail JSONB,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_workflow_audit_version_created_at
    ON workflow_audit(version_id, created_at);

CREATE INDEX IF NOT EXISTS idx_workflow_audit_tenant_created_at
    ON workflow_audit(tenant_id, created_at DESC);

COMMENT ON TABLE workflow_audit IS 'Append-only audit trail for version workflow actions (push, pull, merge, rollback; #2577)';
COMMENT ON COLUMN workflow_audit.action IS 'Workflow verb, e.g. version.push, version.pull, version.merge';
COMMENT ON COLUMN workflow_audit.outcome IS 'success or failure';
COMMENT ON COLUMN workflow_audit.version_id IS 'Primary revision row (versions.id) this event concerns; may be null when N/A';
COMMENT ON COLUMN workflow_audit.detail IS 'Structured context on success; structured error on failure';
