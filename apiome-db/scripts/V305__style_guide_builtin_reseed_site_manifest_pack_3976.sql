-- Re-seed the built-in style guide with the agentic-web site-manifest rule pack -- MFI-18.3 (#3976).
--
-- `CompiledStyleGuide.apply` DROPS a finding whose rule is registered but absent from the
-- read-only "Apiome Recommended" guide, so every new lint pack must be seeded or its findings run
-- and are then discarded. This migration rewrites `seed_builtin_style_guide` with the V304 list
-- plus the site-manifest pack (#3976, six `agents-manifest.*` rules), each at its pack's default
-- severity, and re-seeds every tenant. Custom guides are untouched.
--
-- `apiome-rest/tests/test_data_contract_lint.py` compares this list against the live registry, so
-- the next pack fails CI until it is seeded too.
SET search_path TO apiome, public;

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
        -- OpenAPI / JSON-Schema (schema_lint.OPENAPI_RULES)
        ('compatibility.breaking',                        'error'),
        ('compatibility.unknown',                         'warning'),
        ('documentation.info-missing-description',        'info'),
        ('documentation.operation-missing-summary',       'warning'),
        ('documentation.property-missing-description',    'info'),
        ('documentation.property-missing-example',        'info'),
        ('documentation.schema-missing-description',      'warning'),
        ('naming.property-name',                          'warning'),
        ('naming.schema-pascal-case',                     'warning'),
        ('structure.unbounded-array',                     'warning'),
        -- Cross-format canonical-model pack (lint_engine.CommonRulePack)
        ('common.api-missing-description',                'info'),
        ('common.channel-missing-description',            'info'),
        ('common.field-missing-description',              'info'),
        ('common.message-missing-description',            'info'),
        ('common.operation-missing-description',          'warning'),
        ('common.type-missing-description',               'warning'),
        ('common.unstable-field-name',                    'warning'),
        ('common.unstable-type-name',                     'warning'),
        -- Example-conformance pack (example_conformance_lint), IXH-5.4
        ('examples.non-conforming-example',               'warning'),
        -- Intake-stage pack (intake_lint_rules) -- the source as it arrived
        ('intake.blocked-external-ref',                   'warning'),
        ('intake.overlay-action-invalid',                 'warning'),
        ('intake.overlay-unmatched-target',               'warning'),
        ('intake.unresolved-external-ref',                'warning'),
        -- Data-contract paradigm pack (data_contract_lint), FMT-5.5 #5443
        ('data-contract.classification-missing',          'info'),
        ('data-contract.column-description-coverage',     'warning'),
        ('data-contract.freshness-missing',               'info'),
        ('data-contract.owner-missing',                   'warning'),
        ('data-contract.owner-unresolvable',              'warning'),
        ('data-contract.primary-key-missing',             'warning'),
        ('data-contract.quality-rules-missing',           'warning'),
        ('data-contract.retention-undocumented',          'info'),
        ('data-contract.server-missing',                  'warning'),
        ('data-contract.sla-missing',                     'warning'),
        ('data-contract.status-missing',                  'info'),
        ('data-contract.version-missing',                 'warning'),
        -- GraphQL pack (graphql_lint)
        ('graphql.argument-missing-description',          'info'),
        ('graphql.composition-error',                     'error'),
        ('graphql.composition-invalid-key',               'error'),
        ('graphql.composition-non-shareable-field',       'error'),
        ('graphql.composition-unresolvable-selection',    'error'),
        ('graphql.enum-value-missing-description',        'info'),
        ('graphql.naming-argument-camel-case',            'warning'),
        ('graphql.naming-enum-value-upper-case',          'warning'),
        ('graphql.naming-field-camel-case',               'warning'),
        ('graphql.naming-type-pascal-case',               'warning'),
        ('graphql.require-deprecation-reason',            'warning'),
        -- AsyncAPI pack (asyncapi_lint)
        ('asyncapi.message-missing-name',                 'info'),
        ('asyncapi.message-missing-payload',              'warning'),
        ('asyncapi.message-unstable-name',                'warning'),
        ('asyncapi.server-missing-protocol',              'warning'),
        ('asyncapi.server-missing-security',              'info'),
        -- protobuf pack (proto_lint)
        ('protobuf.editions.closed-enum',                 'warning'),
        ('protobuf.editions.delimited-encoding',          'warning'),
        ('protobuf.editions.legacy-json-format',          'warning'),
        ('protobuf.editions.utf8-validation-off',         'info'),
        ('protobuf.field-no-required',                    'warning'),
        ('protobuf.package-version-suffix',               'warning'),
        ('protobuf.reserved-on-deletion',                 'info'),
        -- Arazzo pack (arazzo_lint)
        ('arazzo.async-source-before-1-1',                'error'),
        ('arazzo.dangling-operation-id',                  'error'),
        ('arazzo.missing-success-criteria',               'warning'),
        ('arazzo.unused-workflow-input',                  'warning'),
        ('arzzo.unresolvable-operation-ref',              'error'),
        -- Kubernetes CRD pack (k8s_crd_lint), IXH-7.2
        ('k8s-crd.required-field-hygiene',                'warning'),
        ('k8s-crd.structural-schema-pruning',             'warning'),
        -- LLM tool-bundle pack (llm_tools_lint), IXH-7.3
        ('llm-tools.duplicate-tool-name',                 'error'),
        ('llm-tools.param-missing-description',           'warning'),
        ('llm-tools.prefer-enum-over-freetext',           'info'),
        ('llm-tools.required-field-hygiene',              'warning'),
        ('llm-tools.tool-missing-description',            'warning'),
        ('llm-tools.tool-weak-description',               'info'),
        -- A2A Agent Card pack (a2a_agent_card_lint), MFI-18.1
        ('a2a.apikey-in-query',                           'warning'),
        ('a2a.duplicate-skill-id',                        'error'),
        ('a2a.insecure-endpoint',                         'warning'),
        ('a2a.missing-required-field',                    'warning'),
        ('a2a.no-security',                               'warning'),
        ('a2a.security-undeclared-scheme',                'error'),
        ('a2a.skill-missing-description',                 'warning'),
        ('a2a.skill-missing-tags',                        'info'),
        ('a2a.skill-without-modes',                       'info'),
        ('a2a.unknown-scheme-type',                       'warning'),
        -- ACP agent manifest pack (acp_agent_lint), MFI-18.2
        ('acp.agent-missing-description',                 'warning'),
        ('acp.capability-missing-description',            'warning'),
        ('acp.duplicate-agent-name',                      'error'),
        ('acp.duplicate-capability-name',                 'warning'),
        ('acp.invalid-agent-name',                        'warning'),
        ('acp.missing-license',                           'info'),
        ('acp.missing-tags',                              'info'),
        ('acp.no-capabilities',                           'info'),
        ('acp.untyped-content',                           'info'),
        -- Agentic-web site-manifest pack (agents_manifest_lint, MFI-18.3)
        ('agents-manifest.broken-endpoint-ref',           'error'),
        ('agents-manifest.duplicate-action-id',           'warning'),
        ('agents-manifest.duplicate-endpoint',            'warning'),
        ('agents-manifest.insecure-endpoint',             'warning'),
        ('agents-manifest.no-agent-endpoints',            'info'),
        ('agents-manifest.undeclared-via',                'error')
    ) AS r(rule_id, severity);
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION apiome.seed_builtin_style_guide(UUID) IS 'Idempotently (re)seed the read-only "Apiome Recommended" style guide and its canonical rule rows for a tenant, from the full built-in rule registry (#4427, refreshed #5443, #3974/#3975, #3976)';

-- Re-seed every existing tenant so the rules that were being dropped start counting.
DO $$
DECLARE
    t RECORD;
BEGIN
    FOR t IN SELECT id FROM apiome.tenants LOOP
        PERFORM apiome.seed_builtin_style_guide(t.id);
    END LOOP;
END;
$$;
