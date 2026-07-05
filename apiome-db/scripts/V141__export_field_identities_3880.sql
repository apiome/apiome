-- Persisted export field identities (#3880, MFX-12.2).
--
-- Problem: protobuf (and later FlatBuffers, Cap'n Proto, Iceberg, FIX Orchestra) require stable
-- positional field identifiers the source may not carry. Re-exporting must reuse prior assignments
-- or every export is wire-incompatible.
--
-- Solution: a tenant-scoped store keyed on (project, export target, canonical field key) that
-- records the synthesized field number assigned on first export. Subsequent exports of the same
-- artifact read the store before emitting; new fields receive the next free number not claimed by
-- source numbers, prior assignments, or ``reserved`` ranges on the message.
--
-- Rollback notes: purely additive. To roll back:
--   DROP TABLE IF EXISTS apiome.export_field_identities;

SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS apiome.export_field_identities (
    id            UUID         NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    tenant_id     UUID         NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    project_id    UUID         NOT NULL REFERENCES apiome.projects(id) ON DELETE CASCADE,
    target        VARCHAR(64)  NOT NULL,
    field_key     VARCHAR(512) NOT NULL,
    field_number  INTEGER      NOT NULL,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT export_field_identities_number_check
        CHECK (field_number >= 1 AND field_number <= 536870911),

    CONSTRAINT uq_export_field_identities_scope
        UNIQUE (tenant_id, project_id, target, field_key)
);

COMMENT ON TABLE apiome.export_field_identities IS
  'Persisted synthesized field identities for export targets (#3880, MFX-12.2). Keys a canonical '
  'field coordinate to the stable number assigned when exporting an artifact to a target that '
  'requires positional identity (proto3 first; reused by later emitters).';

CREATE INDEX IF NOT EXISTS idx_export_field_identities_project_target
  ON apiome.export_field_identities(tenant_id, project_id, target);
