-- Enterprise change reports: approval state, PDF export record and audit trail — #2705 (CR-V2-01).
--
-- Problem: a publication change report (apiome.change_reports, #2700) could be edited and
-- regenerated, but there was no review step before it is handed to outside stakeholders, no
-- record of the PDF that was handed over, and only `edited_at` / `edited_by` to say who touched
-- it. Template changes left no trace at all.
--
-- Solution:
--
--   1. `apiome.change_reports` gains an approval state (draft -> pending_review -> approved),
--      who submitted and approved it and when, the reviewer's note, and the SHA-256 and time of
--      the last PDF export. Every existing report becomes `draft`.
--
--   2. `apiome.change_report_audit` — append-only: one row per report edit, regeneration,
--      submission, approval, rejection and PDF export, and per template creation or default
--      change. Subject ids are plain UUIDs (no foreign key) so history survives deletes.
--
--   3. The `change-report-enterprise` feature flag, the entitlement the REST layer checks when
--      its operator switch is on (same mechanism as `primitives-registry`, V116).
--
-- Idempotent: safe to re-run.

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------
-- 1. Approval state and PDF export record
-- ---------------------------------------------------------------------------------------------

ALTER TABLE apiome.change_reports
    ADD COLUMN IF NOT EXISTS approval_state TEXT NOT NULL DEFAULT 'draft',
    ADD COLUMN IF NOT EXISTS submitted_by UUID REFERENCES apiome.users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS submitted_at TIMESTAMP WITH TIME ZONE,
    ADD COLUMN IF NOT EXISTS approved_by UUID REFERENCES apiome.users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS approved_at TIMESTAMP WITH TIME ZONE,
    ADD COLUMN IF NOT EXISTS review_note TEXT,
    ADD COLUMN IF NOT EXISTS last_pdf_sha256 TEXT,
    ADD COLUMN IF NOT EXISTS last_pdf_exported_at TIMESTAMP WITH TIME ZONE;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'change_reports_approval_state_ck'
          AND conrelid = 'apiome.change_reports'::regclass
    ) THEN
        ALTER TABLE apiome.change_reports
            ADD CONSTRAINT change_reports_approval_state_ck
            CHECK (approval_state IN ('draft', 'pending_review', 'approved'));
    END IF;

    -- An approved report always names its approver's decision time.
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'change_reports_approved_at_ck'
          AND conrelid = 'apiome.change_reports'::regclass
    ) THEN
        ALTER TABLE apiome.change_reports
            ADD CONSTRAINT change_reports_approved_at_ck
            CHECK (approval_state <> 'approved' OR approved_at IS NOT NULL);
    END IF;
END $$;

COMMENT ON COLUMN apiome.change_reports.approval_state IS
    'Review state (#2705): draft, pending_review or approved. Only an approved report can be exported as PDF; an edit or a regeneration returns it to draft.';
COMMENT ON COLUMN apiome.change_reports.submitted_by IS 'User who submitted the report for review; NULL while draft.';
COMMENT ON COLUMN apiome.change_reports.approved_by IS 'Tenant administrator who approved the report; NULL unless approved.';
COMMENT ON COLUMN apiome.change_reports.review_note IS 'Reviewer''s note from the last approval or rejection.';
COMMENT ON COLUMN apiome.change_reports.last_pdf_sha256 IS 'SHA-256 (hex) of the last exported PDF, for reproducibility.';
COMMENT ON COLUMN apiome.change_reports.last_pdf_exported_at IS 'When the last PDF was exported.';

-- ---------------------------------------------------------------------------------------------
-- 2. Audit trail
-- ---------------------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS apiome.change_report_audit (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    project_id UUID,
    change_report_id UUID,
    published_revision_id UUID,
    template_version_id UUID,
    action VARCHAR(96) NOT NULL,
    actor_id UUID REFERENCES apiome.users(id) ON DELETE SET NULL,
    detail JSONB,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_change_report_audit_tenant_created_at
    ON apiome.change_report_audit (tenant_id, created_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_change_report_audit_revision
    ON apiome.change_report_audit (published_revision_id, created_at DESC);

COMMENT ON TABLE apiome.change_report_audit IS
    'Append-only audit trail for change reports and their templates (#2705): report.edit, report.regenerate, report.submit, report.approve, report.reject, report.export_pdf, template.create, template.default_tenant, template.default_project.';
COMMENT ON COLUMN apiome.change_report_audit.change_report_id IS 'Affected change report (apiome.change_reports.id); plain UUID so history survives deletes. NULL for template events.';
COMMENT ON COLUMN apiome.change_report_audit.published_revision_id IS 'Published revision the report belongs to (apiome.versions.id); NULL for template events.';
COMMENT ON COLUMN apiome.change_report_audit.template_version_id IS 'Template version involved, when one is.';
COMMENT ON COLUMN apiome.change_report_audit.actor_id IS 'User who performed the action; NULL when no user is attributable.';
COMMENT ON COLUMN apiome.change_report_audit.detail IS 'Structured context: changed fields, state before and after, reviewer note, PDF hash.';

-- ---------------------------------------------------------------------------------------------
-- 3. Entitlement
-- ---------------------------------------------------------------------------------------------

INSERT INTO apiome.feature_flags (name, label, description, url_patterns, is_preview, enabled)
VALUES
    ('change-report-enterprise',
     'Enterprise change reports',
     'Review and approval of publication change reports, PDF export of approved reports, '
     'and the change-report audit trail.',
     '["/api/versions/*/change-report/submit", "/api/versions/*/change-report/approve", "/api/versions/*/change-report/reject", "/api/versions/*/change-report/pdf", "/api/change-report-audit"]',
     true, true)
ON CONFLICT (name) DO NOTHING;

INSERT INTO apiome.license_feature_flags (license_id, feature_flag_id)
SELECT l.id, ff.id
FROM   apiome.licenses l
CROSS  JOIN apiome.feature_flags ff
WHERE  l.name IN ('Paid', 'Sponsor')
  AND  ff.name = 'change-report-enterprise'
ON CONFLICT DO NOTHING;

DO $$
BEGIN
    RAISE NOTICE 'Enterprise change reports: approval columns, change_report_audit and the change-report-enterprise flag are in place (#2705).';
END $$;
