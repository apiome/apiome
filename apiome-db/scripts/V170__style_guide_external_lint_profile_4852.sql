-- Style-guide external OpenAPI lint profile — CLX-2.2 (#4852).
--
-- Users select baseline | tenant_guide | strict for Spectral/Vacuum/Redocly validation packs.
-- Default baseline keeps existing behaviour when the column is unset on older rows.

SET search_path TO apiome, public;

ALTER TABLE style_guides
    ADD COLUMN IF NOT EXISTS external_lint_profile TEXT NOT NULL DEFAULT 'baseline';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'style_guides_external_lint_profile_ck'
    ) THEN
        ALTER TABLE style_guides
            ADD CONSTRAINT style_guides_external_lint_profile_ck
            CHECK (external_lint_profile IN ('baseline', 'tenant_guide', 'strict'));
    END IF;
END $$;

COMMENT ON COLUMN style_guides.external_lint_profile IS
    'CLX-2.2 OpenAPI external validation pack profile: baseline | tenant_guide | strict (#4852)';
