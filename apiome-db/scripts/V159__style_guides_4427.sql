-- Style-guide data model — GOV-1.1 (#4427).
--
-- Until now lint configuration was a code constant: every tenant scored every spec against
-- the same hard-wired rule set (apiome-rest `schema_lint.RULE_CATALOGUE` plus the canonical
-- rule packs in `lint_engine` / `graphql_lint` / `asyncapi_lint` / `proto_lint` /
-- `arazzo_lint`). Tenant-defined governance needs storage: guides, the rules a guide
-- enables (with per-guide severity overrides and, later, custom rule definitions), and
-- assignments binding a guide tenant-wide or per-project.
--
-- Three tables:
--   * style_guides            — a named rule set owned by a tenant (`source` = builtin|custom)
--   * style_guide_rules       — one row per rule in a guide (enable flag, severity,
--                               optional custom definition for the GOV-1.3 DSL)
--   * style_guide_assignments — binds a guide to a whole tenant or to one project
--
-- Every tenant is seeded with the read-only "Apiome Recommended" builtin guide, whose rows
-- mirror the rule ids and severities the linter ships with today — so existing scores do
-- not change on upgrade. Seeding follows the V118 built-in-roles pattern: an idempotent,
-- self-healing `seed_builtin_style_guide(tenant)` function, called here for every existing
-- tenant and callable on-demand by apiome-rest for tenants created after this migration.
--
-- Severity vocabulary matches the linter's `Severity` type ('error' | 'warning' | 'info' —
-- see apiome-rest `schema_lint.py`), not the abbreviated 'warn' of the design sketch, so
-- seeded rows compare directly against emitted findings.
--
-- The MCP catalog linter (`mcp_lint.py`) is a separate scoring subsystem and is not part
-- of the guide-governed lint surface; its rules are intentionally not seeded here.
SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------
-- style_guides — a named, tenant-owned rule set
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS style_guides (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id   UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name        VARCHAR(255) NOT NULL,
    description TEXT,
    is_default  BOOLEAN NOT NULL DEFAULT false,
    source      TEXT NOT NULL DEFAULT 'custom'
                CONSTRAINT style_guides_source_ck CHECK (source IN ('builtin', 'custom')),
    created_at  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT style_guides_tenant_name_uq UNIQUE (tenant_id, name)
);

COMMENT ON TABLE style_guides IS 'Named lint rule sets (style guides) owned by tenants (#4427)';
COMMENT ON COLUMN style_guides.is_default IS 'The guide used when nothing is assigned; at most one per tenant';
COMMENT ON COLUMN style_guides.source IS 'builtin = shipped read-only (e.g. "Apiome Recommended"); custom = tenant-authored';

-- At most one default guide per tenant.
CREATE UNIQUE INDEX IF NOT EXISTS style_guides_one_default_per_tenant
    ON style_guides (tenant_id) WHERE is_default;

-- At most one builtin guide per tenant; also the seed function's stable lookup key.
CREATE UNIQUE INDEX IF NOT EXISTS style_guides_one_builtin_per_tenant
    ON style_guides (tenant_id) WHERE source = 'builtin';

CREATE INDEX IF NOT EXISTS style_guides_tenant_idx ON style_guides (tenant_id);

-- ---------------------------------------------------------------------------
-- style_guide_rules — the rules a guide enables
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS style_guide_rules (
    id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    guide_id   UUID NOT NULL REFERENCES style_guides(id) ON DELETE CASCADE,
    rule_id    TEXT NOT NULL,
    enabled    BOOLEAN NOT NULL DEFAULT true,
    severity   TEXT NOT NULL
               CONSTRAINT style_guide_rules_severity_ck CHECK (severity IN ('error', 'warning', 'info')),
    custom_def JSONB,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT style_guide_rules_guide_rule_uq UNIQUE (guide_id, rule_id)
);

COMMENT ON TABLE style_guide_rules IS 'Per-guide rule rows: enable flag, severity override, optional custom definition (#4427)';
COMMENT ON COLUMN style_guide_rules.rule_id IS 'Stable dotted rule id (e.g. naming.schema-pascal-case, common.type-missing-description)';
COMMENT ON COLUMN style_guide_rules.severity IS 'Severity this guide assigns the rule: error | warning | info (matches the linter''s Severity type)';
COMMENT ON COLUMN style_guide_rules.custom_def IS 'Spectral-compatible custom rule definition (GOV-1.3); NULL for built-in rules';

-- ---------------------------------------------------------------------------
-- style_guide_assignments — bind a guide tenant-wide or to one project
-- ---------------------------------------------------------------------------
-- Exactly one of tenant_id / project_id is set. A project-level assignment overrides the
-- tenant-wide one; with neither, the tenant's is_default guide applies (GOV-1.4 resolves
-- this chain). Guide/target tenant consistency (an assignment's project belonging to the
-- guide's tenant) is enforced by the service layer, which scopes every lookup by tenant.
CREATE TABLE IF NOT EXISTS style_guide_assignments (
    id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    guide_id   UUID NOT NULL REFERENCES style_guides(id) ON DELETE CASCADE,
    tenant_id  UUID REFERENCES tenants(id) ON DELETE CASCADE,
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT style_guide_assignments_target_ck
        CHECK ((tenant_id IS NULL) <> (project_id IS NULL))
);

COMMENT ON TABLE style_guide_assignments IS 'Binds a style guide to a whole tenant (tenant_id) or one project (project_id) — exactly one target (#4427)';

-- A tenant has at most one tenant-wide assignment; a project at most one assignment.
CREATE UNIQUE INDEX IF NOT EXISTS style_guide_assignments_tenant_uq
    ON style_guide_assignments (tenant_id) WHERE tenant_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS style_guide_assignments_project_uq
    ON style_guide_assignments (project_id) WHERE project_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS style_guide_assignments_guide_idx
    ON style_guide_assignments (guide_id);

-- ---------------------------------------------------------------------------
-- Builtin guide seeding
-- ---------------------------------------------------------------------------
-- Idempotent and self-healing (V118 pattern): (re)creates the read-only "Apiome
-- Recommended" guide for a tenant and rewrites its rule rows to the canonical defaults.
-- Custom guides and their rules are never touched. Called for every existing tenant by
-- this migration and callable on-demand by apiome-rest for tenants created later.
--
-- The rule list mirrors, verbatim, the linter's shipped defaults at the time of this
-- migration: schema_lint.RULE_CATALOGUE (OpenAPI/JSON-Schema) plus the CommonRulePack and
-- the GraphQL / AsyncAPI / protobuf / Arazzo rule packs. Every rule is enabled at the same
-- severity the code constant uses, so a spec scored through this guide produces the exact
-- score it produces today.
CREATE OR REPLACE FUNCTION apiome.seed_builtin_style_guide(p_tenant UUID)
RETURNS void AS $$
DECLARE
    v_guide UUID;
BEGIN
    SELECT id INTO v_guide
      FROM apiome.style_guides
     WHERE tenant_id = p_tenant AND source = 'builtin';

    IF v_guide IS NULL THEN
        -- New guide: it becomes the tenant default only if the tenant has none yet, so a
        -- re-seed never steals default status from a guide the tenant chose later.
        INSERT INTO apiome.style_guides (tenant_id, name, description, is_default, source)
        VALUES (
            p_tenant,
            'Apiome Recommended',
            'The built-in Apiome style guide: every shipped lint rule at its default severity. Read-only; duplicate it to customize.',
            NOT EXISTS (SELECT 1 FROM apiome.style_guides WHERE tenant_id = p_tenant AND is_default),
            'builtin'
        )
        RETURNING id INTO v_guide;
    END IF;

    -- Rewrite the builtin rule rows from scratch (idempotent / self-healing).
    DELETE FROM apiome.style_guide_rules WHERE guide_id = v_guide;

    INSERT INTO apiome.style_guide_rules (guide_id, rule_id, enabled, severity)
    SELECT v_guide, r.rule_id, true, r.severity
    FROM (VALUES
        -- OpenAPI / JSON-Schema (schema_lint.RULE_CATALOGUE)
        ('naming.schema-pascal-case',                    'warning'),
        ('naming.property-name',                         'warning'),
        ('documentation.schema-missing-description',     'warning'),
        ('documentation.property-missing-description',   'info'),
        ('documentation.property-missing-example',       'info'),
        ('documentation.operation-missing-summary',      'warning'),
        ('documentation.info-missing-description',       'info'),
        ('structure.unbounded-array',                    'warning'),
        ('compatibility.breaking',                       'error'),
        ('compatibility.unknown',                        'warning'),
        -- Cross-format canonical-model pack (lint_engine.CommonRulePack)
        ('common.api-missing-description',               'info'),
        ('common.type-missing-description',              'warning'),
        ('common.field-missing-description',             'info'),
        ('common.operation-missing-description',         'warning'),
        ('common.message-missing-description',           'info'),
        ('common.channel-missing-description',           'info'),
        ('common.unstable-type-name',                    'warning'),
        ('common.unstable-field-name',                   'warning'),
        -- GraphQL pack (graphql_lint)
        ('graphql.naming-type-pascal-case',              'warning'),
        ('graphql.naming-field-camel-case',              'warning'),
        ('graphql.naming-argument-camel-case',           'warning'),
        ('graphql.naming-enum-value-upper-case',         'warning'),
        ('graphql.enum-value-missing-description',       'info'),
        ('graphql.argument-missing-description',         'info'),
        ('graphql.require-deprecation-reason',           'warning'),
        -- AsyncAPI pack (asyncapi_lint)
        ('asyncapi.message-missing-name',                'info'),
        ('asyncapi.message-unstable-name',               'warning'),
        ('asyncapi.message-missing-payload',             'warning'),
        ('asyncapi.server-missing-protocol',             'warning'),
        ('asyncapi.server-missing-security',             'info'),
        -- protobuf pack (proto_lint)
        ('protobuf.package-version-suffix',              'warning'),
        ('protobuf.field-no-required',                   'warning'),
        ('protobuf.reserved-on-deletion',                'info'),
        -- Arazzo pack (arazzo_lint). 'arzzo.unresolvable-operation-ref' reproduces the
        -- rule_id exactly as the code emits it (including its typo): rule ids are stable
        -- identifiers that findings are matched on, so the seed must not "fix" it.
        ('arazzo.dangling-operation-id',                 'error'),
        ('arzzo.unresolvable-operation-ref',             'error'),
        ('arazzo.unused-workflow-input',                 'warning'),
        ('arazzo.missing-success-criteria',              'warning')
    ) AS r(rule_id, severity);
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION apiome.seed_builtin_style_guide(UUID) IS 'Idempotently (re)seed the read-only "Apiome Recommended" style guide and its canonical rule rows for a tenant (#4427)';

-- Seed every existing tenant.
DO $$
DECLARE
    t RECORD;
BEGIN
    FOR t IN SELECT id FROM apiome.tenants LOOP
        PERFORM apiome.seed_builtin_style_guide(t.id);
    END LOOP;
END;
$$;
