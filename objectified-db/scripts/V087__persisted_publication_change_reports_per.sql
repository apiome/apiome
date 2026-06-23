-- Persisted publication change reports per published revision (#2700, CR-02)
SET search_path TO odb, public;

CREATE TABLE IF NOT EXISTS change_reports (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    published_revision_id UUID NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
    baseline_revision_id UUID REFERENCES versions(id) ON DELETE SET NULL,
    change_model_json JSONB NOT NULL,
    rendered_body TEXT,
    header_snapshot TEXT,
    footnote_snapshot TEXT,
    edited_rendered_body TEXT,
    edited_header_snapshot TEXT,
    edited_footnote_snapshot TEXT,
    edited_at TIMESTAMP WITH TIME ZONE,
    edited_by UUID REFERENCES users(id) ON DELETE SET NULL,
    template_version_id UUID,
    rendered_at TIMESTAMP WITH TIME ZONE,
    regenerated_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT change_reports_published_revision_unique UNIQUE (published_revision_id)
);

CREATE INDEX IF NOT EXISTS idx_change_reports_tenant_project
    ON change_reports(tenant_id, project_id);

COMMENT ON TABLE change_reports IS 'Publication change report artifacts per published schema revision (#2700); one row per published_revision_id';
COMMENT ON COLUMN change_reports.published_revision_id IS 'Natural key: the published version row (versions.id); idempotent with ON CONFLICT';
COMMENT ON COLUMN change_reports.baseline_revision_id IS 'Prior revision compared against at publication time; nullable when first publish';
COMMENT ON COLUMN change_reports.change_model_json IS 'Immutable ChangeReportModel JSON after first insert; source for regenerate';
COMMENT ON COLUMN change_reports.rendered_body IS 'Last template render output (body)';
COMMENT ON COLUMN change_reports.header_snapshot IS 'Last template render header';
COMMENT ON COLUMN change_reports.footnote_snapshot IS 'Last template render footnote';
COMMENT ON COLUMN change_reports.edited_rendered_body IS 'User override full snapshot for body; NULL means use rendered_body';
COMMENT ON COLUMN change_reports.edited_header_snapshot IS 'User override full snapshot for header';
COMMENT ON COLUMN change_reports.edited_footnote_snapshot IS 'User override full snapshot for footnote';
COMMENT ON COLUMN change_reports.template_version_id IS 'Optional template version reference (CR-03); no FK until template tables exist';

-- Rollback: DROP TABLE IF EXISTS odb.change_reports CASCADE;
