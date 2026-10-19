-- Schema subject model — CDG-4.2 (#5974).
--
-- A schema registry needs what the catalog does not have yet: named **subjects**, integer **schema
-- ids**, fingerprint-idempotent registration and a **compatibility level** per subject. This
-- migration adds them without a second store for schema bytes: a subject version always points at a
-- catalog item revision (`projects` + `versions`), the same row the import pipeline writes for an
-- Avro, JSON Schema or Protobuf upload. One catalog.
--
--   schema_registry_config    per tenant: default compatibility level, default mode, id counter
--   schema_registry_schemas   per tenant: one row per distinct schema (schema_id ↔ fingerprint)
--   schema_subjects           per tenant: named subjects (strategy, level, mode, backing item)
--   schema_subject_versions   per subject: version n → schema_id + the revision that holds it
--
-- Ids. `schema_id` is a small integer allocated from a per-tenant counter
-- (`schema_registry_config.next_schema_id`), so a client sees 1, 2, 3 … within its tenant. A schema id
-- names *content*, not a subject: registering an identical fingerprint returns the existing id, and
-- two subjects holding the same schema share one id. That is why ids live in their own table
-- (UNIQUE (tenant, schema_id) and (tenant, schema_type, fingerprint)) and a subject version only
-- references one — a subject lists an id at most once.
--
-- Fingerprint. `fingerprint_kind` records how the fingerprint was computed. Today every row is
-- `canonical-model` (the import pipeline's canonical-model fingerprint). Avro's Parsing Canonical
-- Form arrives with MFI-12.1 (#3782) as `avro-pcf`; it is a new kind, never silently substituted for
-- an existing one, so a fingerprint lookup always compares like with like.
--
-- Deletion. A soft-deleted subject (`deleted_at`) and its versions drop out of lists, but the schema
-- row stays, so an id keeps resolving. Subject names are unique among live subjects only, so a
-- deleted name can be registered again.
--
-- Compatibility verdicts are not computed here (CDG-4.3); `compatibility_level` is stored only.
--
-- Rollback notes:
--   DROP TABLE IF EXISTS apiome.schema_subject_versions;
--   DROP TABLE IF EXISTS apiome.schema_subjects;
--   DROP TABLE IF EXISTS apiome.schema_registry_schemas;
--   DROP TABLE IF EXISTS apiome.schema_registry_config;

SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS schema_registry_config (
    tenant_id UUID PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,

    compatibility_level VARCHAR(24) NOT NULL DEFAULT 'BACKWARD'
        CONSTRAINT schema_registry_config_level_ck CHECK (
            compatibility_level IN (
                'NONE', 'BACKWARD', 'BACKWARD_TRANSITIVE', 'FORWARD', 'FORWARD_TRANSITIVE',
                'FULL', 'FULL_TRANSITIVE'
            )
        ),
    mode VARCHAR(16) NOT NULL DEFAULT 'READWRITE'
        CONSTRAINT schema_registry_config_mode_ck CHECK (mode IN ('READWRITE', 'READONLY')),

    -- The next schema id this tenant hands out (the per-tenant sequence).
    next_schema_id INTEGER NOT NULL DEFAULT 1
        CONSTRAINT schema_registry_config_next_id_ck CHECK (next_schema_id >= 1),

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS schema_registry_schemas (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    schema_id INTEGER NOT NULL CONSTRAINT schema_registry_schemas_id_ck CHECK (schema_id >= 1),

    schema_type VARCHAR(16) NOT NULL
        CONSTRAINT schema_registry_schemas_type_ck CHECK (schema_type IN ('AVRO', 'JSON', 'PROTOBUF')),
    fingerprint VARCHAR(128) NOT NULL,
    fingerprint_kind VARCHAR(32) NOT NULL DEFAULT 'canonical-model'
        CONSTRAINT schema_registry_schemas_fp_kind_ck CHECK (
            fingerprint_kind IN ('canonical-model', 'avro-pcf')
        ),

    -- The catalog item revision that first held this schema.
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    version_record_id UUID NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
    "references" JSONB NOT NULL DEFAULT '[]'::jsonb
        CONSTRAINT schema_registry_schemas_refs_ck CHECK (jsonb_typeof("references") = 'array'),

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT schema_registry_schemas_tenant_id_uq UNIQUE (tenant_id, schema_id),
    CONSTRAINT schema_registry_schemas_fingerprint_uq UNIQUE (tenant_id, schema_type, fingerprint_kind, fingerprint)
);

CREATE TABLE IF NOT EXISTS schema_subjects (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    name VARCHAR(255) NOT NULL
        CONSTRAINT schema_subjects_name_ck CHECK (length(btrim(name)) > 0 AND name !~ '[[:cntrl:]]'),
    -- Confluent subject naming strategy (MFX-19.3): topic / record / topic_record. NULL = not stated.
    strategy VARCHAR(16)
        CONSTRAINT schema_subjects_strategy_ck CHECK (strategy IN ('topic', 'record', 'topic_record')),
    -- NULL = the tenant default (schema_registry_config.compatibility_level).
    compatibility_level VARCHAR(24)
        CONSTRAINT schema_subjects_level_ck CHECK (
            compatibility_level IN (
                'NONE', 'BACKWARD', 'BACKWARD_TRANSITIVE', 'FORWARD', 'FORWARD_TRANSITIVE',
                'FULL', 'FULL_TRANSITIVE'
            )
        ),
    mode VARCHAR(16) NOT NULL DEFAULT 'READWRITE'
        CONSTRAINT schema_subjects_mode_ck CHECK (mode IN ('READWRITE', 'READONLY')),

    -- The catalog item new versions are registered into (created on first registration, or the
    -- item attached to the subject). NULL until then.
    project_id UUID REFERENCES projects(id) ON DELETE SET NULL,

    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_schema_subjects_live_name
    ON schema_subjects (tenant_id, name) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_schema_subjects_project ON schema_subjects (project_id);

CREATE TABLE IF NOT EXISTS schema_subject_versions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    subject_id UUID NOT NULL REFERENCES schema_subjects(id) ON DELETE CASCADE,
    version INTEGER NOT NULL CONSTRAINT schema_subject_versions_version_ck CHECK (version >= 1),
    schema_id INTEGER NOT NULL,

    -- The catalog item revision that holds this version's schema.
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    version_record_id UUID NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
    schema_type VARCHAR(16) NOT NULL
        CONSTRAINT schema_subject_versions_type_ck CHECK (schema_type IN ('AVRO', 'JSON', 'PROTOBUF')),
    fingerprint VARCHAR(128) NOT NULL,
    "references" JSONB NOT NULL DEFAULT '[]'::jsonb
        CONSTRAINT schema_subject_versions_refs_ck CHECK (jsonb_typeof("references") = 'array'),

    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMPTZ,

    CONSTRAINT schema_subject_versions_version_uq UNIQUE (subject_id, version),
    CONSTRAINT schema_subject_versions_schema_uq UNIQUE (subject_id, schema_id),
    CONSTRAINT schema_subject_versions_schema_fk FOREIGN KEY (tenant_id, schema_id)
        REFERENCES schema_registry_schemas (tenant_id, schema_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_schema_subject_versions_schema
    ON schema_subject_versions (tenant_id, schema_id);
CREATE INDEX IF NOT EXISTS idx_schema_subject_versions_revision
    ON schema_subject_versions (version_record_id);

COMMENT ON TABLE schema_registry_config IS
    'CDG-4.2 (#5974): per-tenant schema registry defaults (compatibility level, mode) and the per-tenant schema id counter.';
COMMENT ON TABLE schema_registry_schemas IS
    'CDG-4.2 (#5974): one row per distinct schema of a tenant; schema_id names content and is shared by every subject holding it.';
COMMENT ON TABLE schema_subjects IS
    'CDG-4.2 (#5974): named schema registry subjects; compatibility_level NULL = tenant default. Names unique among live subjects.';
COMMENT ON TABLE schema_subject_versions IS
    'CDG-4.2 (#5974): subject version n -> schema_id and the catalog item revision (project_id, version_record_id) that holds it.';
COMMENT ON COLUMN schema_registry_schemas.fingerprint_kind IS
    'canonical-model today; avro-pcf once MFI-12.1 (#3782) ships. Kinds are never mixed in a lookup.';
