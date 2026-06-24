-- Granular RBAC: access audit log (#3611, RC1-1.1)
--
-- Append-only, hash-chained ledger of access & permission events: role assignments, permission
-- (matrix) changes, member lifecycle, permission denials, and platform-admin overrides. Mirrors the
-- workflow_audit / registry_audit ledgers but is scoped to access control and is intended as SOC 2 /
-- ISO 27001 access-review evidence.
--
-- Each row carries the hash of the previous row in the same tenant chain plus its own entry hash, so
-- tampering (an edited or deleted row) is detectable. Writes are best-effort from objectified-rest: a
-- failed audit insert must never fail the governed action it records.
--
-- Event types (action): role.assigned, role.created, role.updated, role.deleted, permission.changed,
-- member.invited, member.suspended, member.reinstated, member.offboarded, permission.denied,
-- admin.override.
SET search_path TO odb, public;

CREATE TABLE IF NOT EXISTS access_audit (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE,
    actor_id UUID REFERENCES users(id) ON DELETE SET NULL,
    actor_label VARCHAR(255),
    action VARCHAR(64) NOT NULL,
    target VARCHAR(512),
    source VARCHAR(32) NOT NULL DEFAULT 'web',
    detail JSONB,
    prev_hash VARCHAR(64),
    entry_hash VARCHAR(64),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_access_audit_tenant_created_at
    ON access_audit(tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_access_audit_action
    ON access_audit(action);

COMMENT ON TABLE access_audit IS 'Append-only, hash-chained access & permission audit ledger (#3611)';
COMMENT ON COLUMN access_audit.tenant_id IS 'Tenant the event belongs to; null for platform-plane events without a tenant scope';
COMMENT ON COLUMN access_audit.actor_id IS 'User who performed the action; null for system/SCIM/anonymous sources';
COMMENT ON COLUMN access_audit.actor_label IS 'Display label for the actor (email, "system", "platform-admin") retained independent of the users row';
COMMENT ON COLUMN access_audit.action IS 'Event type, e.g. role.assigned, permission.changed, member.suspended, permission.denied, admin.override';
COMMENT ON COLUMN access_audit.target IS 'Subject of the event (affected user email, role name, resource:action, version coordinate, ...)';
COMMENT ON COLUMN access_audit.source IS 'Origin of the action: web, api_key, sso, scim, admin (platform plane), system';
COMMENT ON COLUMN access_audit.detail IS 'Structured context (changed cells, old/new role, reason, request metadata)';
COMMENT ON COLUMN access_audit.prev_hash IS 'entry_hash of the previous row in this tenant chain (hash-chaining for tamper-evidence)';
COMMENT ON COLUMN access_audit.entry_hash IS 'SHA-256 over (prev_hash, tenant_id, actor, action, target, detail, created_at)';
