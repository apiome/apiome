-- Database Data Storage: class_schema, data_record, data_snapshot
-- See Database Data Storage Implementation Plan

SET search_path TO odb, public;

-- Enum for data_record action (created, updated, deleted)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'data_record_action') THEN
        CREATE TYPE data_record_action AS ENUM ('created', 'updated', 'deleted');
    END IF;
END $$;

-- class_schema: frozen JSON Schema 2020-12 per class, per version (created on publish)
CREATE TABLE IF NOT EXISTS class_schema (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    version_id UUID NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
    class_id UUID NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
    schema JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT class_schema_version_class_unique UNIQUE (version_id, class_id)
);

COMMENT ON TABLE class_schema IS 'Frozen JSON Schema 2020-12 per class per version; populated when version is published';
COMMENT ON COLUMN class_schema.id IS 'Unique identifier for the class schema record';
COMMENT ON COLUMN class_schema.version_id IS 'Version this schema belongs to';
COMMENT ON COLUMN class_schema.class_id IS 'Source class (unique per version)';
COMMENT ON COLUMN class_schema.schema IS 'Full JSON Schema 2020-12 document';
COMMENT ON COLUMN class_schema.created_at IS 'Set on first publish';
COMMENT ON COLUMN class_schema.updated_at IS 'Updated on re-publish';

CREATE INDEX IF NOT EXISTS idx_class_schema_version_id ON class_schema(version_id);
CREATE INDEX IF NOT EXISTS idx_class_schema_class_id ON class_schema(class_id);
CREATE INDEX IF NOT EXISTS idx_class_schema_schema ON class_schema USING GIN (schema);

-- data_record: event log per logical record (one row per created/updated/deleted event)
CREATE TABLE IF NOT EXISTS data_record (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    record_id UUID NOT NULL,
    class_schema_id UUID NOT NULL REFERENCES class_schema(id) ON DELETE RESTRICT,
    action data_record_action NOT NULL,
    record_sequence INT NOT NULL,
    data JSONB,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_by UUID REFERENCES users(id) ON DELETE SET NULL
);

COMMENT ON TABLE data_record IS 'Event-sourced log: one row per created/updated/deleted event per logical record';
COMMENT ON COLUMN data_record.id IS 'Unique identifier for the event row';
COMMENT ON COLUMN data_record.record_id IS 'Logical record id; same for all events of one instance';
COMMENT ON COLUMN data_record.class_schema_id IS 'Frozen class schema this record follows';
COMMENT ON COLUMN data_record.action IS 'created, updated, or deleted';
COMMENT ON COLUMN data_record.record_sequence IS 'Per-record sequence (1, 2, 3, …); first event is 1 and always created';
COMMENT ON COLUMN data_record.data IS 'Full payload for created, delta for updated, optional for deleted';
COMMENT ON COLUMN data_record.tenant_id IS 'Tenant for RLS and filtering';
COMMENT ON COLUMN data_record.created_by IS 'User who created this event (optional)';

CREATE INDEX IF NOT EXISTS idx_data_record_record_id_sequence ON data_record(record_id, record_sequence);
CREATE INDEX IF NOT EXISTS idx_data_record_class_schema_id ON data_record(class_schema_id);
CREATE INDEX IF NOT EXISTS idx_data_record_tenant_id ON data_record(tenant_id);
CREATE INDEX IF NOT EXISTS idx_data_record_created_at ON data_record(created_at);

-- data_snapshot: current state per logical record (row removed on delete, recreated on restore)
CREATE TABLE IF NOT EXISTS data_snapshot (
    record_id UUID PRIMARY KEY,
    class_schema_id UUID NOT NULL REFERENCES class_schema(id) ON DELETE RESTRICT,
    data JSONB NOT NULL,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE data_snapshot IS 'Current full state per logical record; deleted when record is soft-deleted, recreated on restore';
COMMENT ON COLUMN data_snapshot.record_id IS 'Same as data_record.record_id';
COMMENT ON COLUMN data_snapshot.class_schema_id IS 'Same as latest data_record for this record_id';
COMMENT ON COLUMN data_snapshot.data IS 'Current full document';
COMMENT ON COLUMN data_snapshot.tenant_id IS 'Tenant for RLS; in sync with data_record';

CREATE INDEX IF NOT EXISTS idx_data_snapshot_class_schema_id ON data_snapshot(class_schema_id);
CREATE INDEX IF NOT EXISTS idx_data_snapshot_tenant_id ON data_snapshot(tenant_id);
CREATE INDEX IF NOT EXISTS idx_data_snapshot_updated_at ON data_snapshot(updated_at);
