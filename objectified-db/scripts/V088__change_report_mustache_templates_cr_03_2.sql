-- Change report Mustache templates (CR-03, #2701)
SET search_path TO odb, public;

CREATE TABLE IF NOT EXISTS change_report_template_versions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    owner_tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE,
    semver TEXT NOT NULL,
    header_template TEXT NOT NULL,
    body_template TEXT NOT NULL,
    footnote_template TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by UUID REFERENCES users(id) ON DELETE SET NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_crtv_system_semver
    ON change_report_template_versions (semver)
    WHERE owner_tenant_id IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_crtv_tenant_semver
    ON change_report_template_versions (owner_tenant_id, semver)
    WHERE owner_tenant_id IS NOT NULL;

COMMENT ON TABLE change_report_template_versions IS 'Mustache templates for publication change reports (#2701); system rows have owner_tenant_id NULL';

ALTER TABLE tenants
    ADD COLUMN IF NOT EXISTS change_report_template_version_id UUID
        REFERENCES change_report_template_versions(id) ON DELETE SET NULL;

ALTER TABLE projects
    ADD COLUMN IF NOT EXISTS change_report_template_version_id UUID
        REFERENCES change_report_template_versions(id) ON DELETE SET NULL;

COMMENT ON COLUMN tenants.change_report_template_version_id IS 'Optional tenant default template; project may override (#2701)';
COMMENT ON COLUMN projects.change_report_template_version_id IS 'Optional project-level template override (#2701)';
