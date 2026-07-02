-- Migration plans: persisted rules for migrating data from one version to another.
-- Enables running migrations outside the migration canvas (e.g. backend jobs).

SET search_path TO apiome, public;

-- migration_plans: one row per (project, from_version, to_version)
CREATE TABLE IF NOT EXISTS migration_plans (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    from_version_id UUID NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
    to_version_id UUID NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT migration_plans_version_pair_unique UNIQUE (project_id, from_version_id, to_version_id)
);

COMMENT ON TABLE migration_plans IS 'One plan per project and version pair (from → to); holds rules per class';
COMMENT ON COLUMN migration_plans.from_version_id IS 'Source schema version';
COMMENT ON COLUMN migration_plans.to_version_id IS 'Target schema version';

CREATE INDEX IF NOT EXISTS idx_migration_plans_project ON migration_plans(project_id);
CREATE INDEX IF NOT EXISTS idx_migration_plans_from_version ON migration_plans(from_version_id);
CREATE INDEX IF NOT EXISTS idx_migration_plans_to_version ON migration_plans(to_version_id);

-- migration_plan_rules: one row per (plan, class_name, source_property); rule JSONB holds full rule
CREATE TABLE IF NOT EXISTS migration_plan_rules (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    migration_plan_id UUID NOT NULL REFERENCES migration_plans(id) ON DELETE CASCADE,
    class_name VARCHAR(255) NOT NULL,
    source_property VARCHAR(255) NOT NULL,
    rule JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT migration_plan_rules_plan_class_prop_unique UNIQUE (migration_plan_id, class_name, source_property)
);

COMMENT ON TABLE migration_plan_rules IS 'Rules per class and source property; rule has name, inputProperties, ruleType, ruleContent, outputProperties';
COMMENT ON COLUMN migration_plan_rules.class_name IS 'Class (schema) name this rule applies to';
COMMENT ON COLUMN migration_plan_rules.source_property IS 'Source property name (key for the edge, e.g. zipcode)';
COMMENT ON COLUMN migration_plan_rules.rule IS 'Full rule: name?, inputProperties[], ruleType, ruleContent, outputProperties[]';

CREATE INDEX IF NOT EXISTS idx_migration_plan_rules_plan ON migration_plan_rules(migration_plan_id);
CREATE INDEX IF NOT EXISTS idx_migration_plan_rules_class ON migration_plan_rules(migration_plan_id, class_name);
