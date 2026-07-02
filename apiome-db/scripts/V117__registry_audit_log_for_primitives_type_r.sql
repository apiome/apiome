-- Registry audit log for primitives / type-registry governance (#3481, 7.4)
--
-- Append-only ledger of governed registry actions (create / update / delete / import) on
-- apiome.primitives, with the acting user (actor) and a timestamp. Mirrors the workflow_audit
-- ledger (#2577) but is scoped to the type registry: each row optionally references the
-- affected primitive and carries its derived $id / namespace for traceability even after the
-- primitive row itself is deleted.
--
-- Writes are best-effort from apiome-rest (a failed audit insert must never fail the
-- governed action it records). The list endpoint GET /v1/primitives/{tenant_slug}/audit reads
-- this table, tenant-scoped, newest first.
SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS registry_audit (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    primitive_id UUID,
    schema_id TEXT,
    namespace TEXT,
    action VARCHAR(96) NOT NULL,
    outcome VARCHAR(24) NOT NULL,
    actor_id UUID REFERENCES users(id) ON DELETE SET NULL,
    detail JSONB,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_registry_audit_tenant_created_at
    ON registry_audit(tenant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_registry_audit_primitive_created_at
    ON registry_audit(primitive_id, created_at DESC);

COMMENT ON TABLE registry_audit IS 'Append-only audit trail for type-registry / primitives governance actions (create, update, delete, import; #3481)';
COMMENT ON COLUMN registry_audit.primitive_id IS 'Affected primitive (apiome.primitives.id); may be null for whole-document imports or after the primitive is deleted';
COMMENT ON COLUMN registry_audit.schema_id IS 'Derived JSON Schema $id of the affected type, retained for traceability independent of the primitive row';
COMMENT ON COLUMN registry_audit.namespace IS 'Registry namespace path of the affected type, when applicable';
COMMENT ON COLUMN registry_audit.action IS 'Registry verb, e.g. primitive.create, primitive.update, primitive.delete, primitive.import';
COMMENT ON COLUMN registry_audit.outcome IS 'success or failure';
COMMENT ON COLUMN registry_audit.actor_id IS 'User who performed the action; null for API-key actions without an attributable user';
COMMENT ON COLUMN registry_audit.detail IS 'Structured context (e.g. changed fields, import counts) on success; structured error on failure';
