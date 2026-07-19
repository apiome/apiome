-- =============================================================================
-- V186: Operational component library data model (DCW-3.1, private-suite#2353)
-- =============================================================================
-- Tenant-scoped library of reusable OpenAPI *operational* components —
-- parameters, headers, request bodies, responses, and security bundles —
-- plus pinned references to existing Type Registry entries for schemas.
-- The library is modeled separately from project versions:
--
--   * apiome.operational_components            — stable component identity
--   * apiome.operational_component_revisions   — semver revisions with the
--     minimal MVP lifecycle (draft -> published; published is immutable)
--   * apiome.version_component_pins            — a project draft revision
--     pins one published library revision (ON DELETE RESTRICT backstops the
--     "in-use revisions cannot be deleted" rule at the database level)
--   * apiome.component_library_audit           — append-only ledger for
--     lifecycle and pin mutations (mirrors apiome.registry_audit /
--     apiome.source_change_audit)
--
-- Schema-kind revisions pin an existing apiome.primitives row (the Type
-- Registry stays authoritative; this is a pinned reference, not a second
-- schema registry) and snapshot its JSON Schema payload so a published
-- revision keeps materializing identically even when the registry head
-- moves. Single-file export materializes pinned revisions under standard
-- local `components` with collision-safe naming and optional
-- `x-apiome-origin` metadata (enforced in apiome-rest, not here).

SET search_path TO apiome, public;

-- -----------------------------------------------------------------------------
-- Component identity
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS apiome.operational_components (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    description TEXT,
    owner_id UUID REFERENCES apiome.users(id) ON DELETE SET NULL,
    created_by UUID REFERENCES apiome.users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMPTZ,
    CONSTRAINT operational_component_kind CHECK (
        kind IN ('parameter', 'header', 'requestBody', 'response', 'securityBundle', 'schema')
    ),
    CONSTRAINT operational_component_name_shape CHECK (
        name ~ '^[A-Za-z][A-Za-z0-9_.-]{0,127}$'
    )
);

COMMENT ON TABLE apiome.operational_components IS
    'Tenant-scoped reusable operational component identity (DCW-3.1, private-suite#2353). '
    'Kinds: parameter | header | requestBody | response | securityBundle | schema. '
    'Schema-kind components are pinned references into the Type Registry (apiome.primitives), '
    'not a second schema registry.';
COMMENT ON COLUMN apiome.operational_components.name IS
    'Stable library name; also the preferred local components key at materialization '
    '(OpenAPI component-key safe: ^[A-Za-z][A-Za-z0-9_.-]*$).';
COMMENT ON COLUMN apiome.operational_components.kind IS
    'The OAS kind this component materializes under (components.parameters / headers / '
    'requestBodies / responses / securitySchemes / schemas).';
COMMENT ON COLUMN apiome.operational_components.owner_id IS
    'The member accountable for the component''s lifecycle (defaults to the creator).';
COMMENT ON COLUMN apiome.operational_components.deleted_at IS
    'Soft delete; blocked while any live pin references one of the component''s revisions.';

CREATE UNIQUE INDEX IF NOT EXISTS uq_operational_components_live_name
    ON apiome.operational_components (tenant_id, kind, name)
    WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_operational_components_tenant
    ON apiome.operational_components (tenant_id, kind)
    WHERE deleted_at IS NULL;

-- -----------------------------------------------------------------------------
-- Component revisions (minimal MVP lifecycle: draft -> published, immutable)
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS apiome.operational_component_revisions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    component_id UUID NOT NULL REFERENCES apiome.operational_components(id) ON DELETE CASCADE,
    revision TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'draft',
    canonical_payload JSONB NOT NULL,
    schema_primitive_id UUID REFERENCES apiome.primitives(id) ON DELETE RESTRICT,
    payload_digest TEXT NOT NULL,
    published_at TIMESTAMPTZ,
    published_by UUID REFERENCES apiome.users(id) ON DELETE SET NULL,
    created_by UUID REFERENCES apiome.users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT operational_component_revision_semver CHECK (
        revision ~ '^[0-9]+\.[0-9]+\.[0-9]+$'
    ),
    CONSTRAINT operational_component_revision_state CHECK (
        state IN ('draft', 'published')
    ),
    CONSTRAINT uq_operational_component_revision UNIQUE (component_id, revision)
);

COMMENT ON TABLE apiome.operational_component_revisions IS
    'Semver-like revisions of an operational component (DCW-3.1). draft rows are editable; '
    'published rows are immutable — payload updates and deletion are rejected in apiome-rest, '
    'and pins may only target published revisions. Publishing requires a revision strictly '
    'greater than the component''s highest published revision (no unsafe downgrades).';
COMMENT ON COLUMN apiome.operational_component_revisions.revision IS
    'Semver revision string (MAJOR.MINOR.PATCH), unique per component.';
COMMENT ON COLUMN apiome.operational_component_revisions.canonical_payload IS
    'The canonical OAS fragment this revision materializes (for schema-kind components: the '
    'JSON Schema snapshotted from the pinned Type Registry entry, so later registry-head '
    'changes never mutate projects pinned to this revision).';
COMMENT ON COLUMN apiome.operational_component_revisions.schema_primitive_id IS
    'For schema-kind components: the pinned apiome.primitives row this revision snapshots. '
    'ON DELETE RESTRICT keeps a pinned Type Registry entry from being deleted while referenced.';
COMMENT ON COLUMN apiome.operational_component_revisions.payload_digest IS
    'Algorithm-prefixed digest (sha256:<hex>) of the canonical payload, for cheap equality '
    'and audit binding.';

CREATE INDEX IF NOT EXISTS idx_operational_component_revisions_component
    ON apiome.operational_component_revisions (component_id, state);

CREATE INDEX IF NOT EXISTS idx_operational_component_revisions_tenant
    ON apiome.operational_component_revisions (tenant_id);

-- -----------------------------------------------------------------------------
-- Project pins (a version uses exactly the revision it pinned)
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS apiome.version_component_pins (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    version_id UUID NOT NULL REFERENCES apiome.versions(id) ON DELETE CASCADE,
    component_revision_id UUID NOT NULL
        REFERENCES apiome.operational_component_revisions(id) ON DELETE RESTRICT,
    local_name TEXT,
    created_by UUID REFERENCES apiome.users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMPTZ,
    CONSTRAINT version_component_pin_local_name_shape CHECK (
        local_name IS NULL OR local_name ~ '^[A-Za-z][A-Za-z0-9_.-]{0,127}$'
    )
);

COMMENT ON TABLE apiome.version_component_pins IS
    'A project version''s use of one published library revision (DCW-3.1). The pin is '
    'immutable identity: updating a library head never mutates versions pinned to older '
    'revisions. ON DELETE RESTRICT on component_revision_id is the database backstop for '
    'the "in-use revisions cannot be deleted" acceptance rule.';
COMMENT ON COLUMN apiome.version_component_pins.local_name IS
    'Optional preferred local components key; materialization falls back to the component '
    'name and always resolves collisions deterministically without overwriting local '
    'components.';
COMMENT ON COLUMN apiome.version_component_pins.deleted_at IS
    'Soft delete (unpin). Only live pins participate in materialization and in-use checks.';

CREATE UNIQUE INDEX IF NOT EXISTS uq_version_component_pin_live
    ON apiome.version_component_pins (version_id, component_revision_id)
    WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_version_component_pins_version
    ON apiome.version_component_pins (version_id)
    WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_version_component_pins_revision
    ON apiome.version_component_pins (component_revision_id)
    WHERE deleted_at IS NULL;

-- -----------------------------------------------------------------------------
-- Append-only audit ledger
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS apiome.component_library_audit (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    component_id UUID,
    revision_id UUID,
    version_id UUID,
    actor_id UUID REFERENCES apiome.users(id) ON DELETE SET NULL,
    action TEXT NOT NULL,
    outcome TEXT NOT NULL DEFAULT 'success',
    detail JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE apiome.component_library_audit IS
    'Append-only ledger for component-library lifecycle and pin mutations (DCW-3.1): '
    'component.create, component.delete, revision.draft, revision.update, revision.publish, '
    'revision.delete, pin.create, pin.remove. Written in the same transaction as the '
    'mutation it records. Subject ids are plain UUIDs (no FK) so history survives deletes.';
COMMENT ON COLUMN apiome.component_library_audit.detail IS
    'Structured context: revision semver, payload digest, pin/version ids, blocker counts.';

CREATE INDEX IF NOT EXISTS idx_component_library_audit_tenant
    ON apiome.component_library_audit (tenant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_component_library_audit_component
    ON apiome.component_library_audit (component_id, created_at DESC);
