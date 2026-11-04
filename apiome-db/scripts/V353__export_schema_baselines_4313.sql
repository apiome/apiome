-- Persisted SQL changelog export baselines (#4313, MFX-35.3).
--
-- Problem: a one-shot DDL dump is not how teams apply schema changes. The SQL DDL export's
-- Liquibase and Flyway modes write migration changesets, and a re-export after a model change must
-- write only the delta — so each export needs to know what the previous one wrote.
--
-- Solution: a tenant-scoped store keyed on (project, export target, variant) holding the last
-- exported baseline as JSON: the canonical model, its relational projection, and the changeset /
-- Flyway version counters. The variant is the dialect and changelog mode (``postgres:liquibase``),
-- so each one advances independently. Every real (non-preview) export in a changelog mode replaces
-- the row; the next export diffs against it. Mirrors ``export_field_identities`` (MFX-12.2, V141).
--
-- Rollback notes: purely additive. To roll back:
--   DROP TABLE IF EXISTS apiome.export_schema_baselines;

SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS apiome.export_schema_baselines (
    id            UUID         NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    tenant_id     UUID         NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    project_id    UUID         NOT NULL REFERENCES apiome.projects(id) ON DELETE CASCADE,
    target        VARCHAR(64)  NOT NULL,
    variant       VARCHAR(64)  NOT NULL,
    baseline      JSONB        NOT NULL,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT uq_export_schema_baselines_scope
        UNIQUE (tenant_id, project_id, target, variant)
);

COMMENT ON TABLE apiome.export_schema_baselines IS
  'Last exported SQL changelog baseline per artifact, target and variant (#4313, MFX-35.3): the '
  'canonical model, relational projection and changeset counters the next Liquibase / Flyway export '
  'diffs against to write only the delta.';

CREATE INDEX IF NOT EXISTS idx_export_schema_baselines_project
  ON apiome.export_schema_baselines(tenant_id, project_id);
