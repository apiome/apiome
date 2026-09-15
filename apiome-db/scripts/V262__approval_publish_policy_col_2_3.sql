-- =====================================================================================
-- V262 — Approval policy on style guides (COL-2.3, #4519)
-- =====================================================================================
--
-- COL-2.1 (#4517) records who approved a draft version, but nothing makes that record
-- binding: an author can publish a version no reviewer ever looked at. COL-2.3 adds the
-- governance setting that turns a review outcome into a publish gate.
--
-- Two columns, one policy:
--   required_approvals     — how many current-round approvals a draft needs before it may
--                            be published. 0 (DEFAULT) switches the gate off entirely, which
--                            is exactly today's behaviour, so the migration changes nothing
--                            until a tenant opts in.
--   required_reviewer_role — an optional RBAC role slug (`roles.slug`, V118) that at least
--                            one of those approvals must come from, e.g. `release-manager`.
--                            NULL means any approver counts. Only meaningful while
--                            required_approvals >= 1.
--
-- These sit on `style_guides` beside the CTG-3.4 (#4478) `breaking_publish_policy` column
-- for the same reason it does: publish-time governance resolves through the GOV-1.4 guide
-- chain (project assignment → tenant assignment → tenant default), which gives per-project
-- escalation for free and keeps every publish gate on one editable surface. A deliberately
-- loose FK-less reference to `roles.slug`: the slug is only compared, never joined, so a
-- renamed or deleted role degrades to "nobody holds it" (publish blocked, force available)
-- rather than to a migration-time cascade on a governance setting.
--
-- The gate itself, its 422 contract and its audit trail live in apiome-rest
-- (`app.approval_publish_gate`); this SQL only has to be additive, defaulted to "off", and
-- constrained.
--
-- Rollback notes (additive only):
--   ALTER TABLE apiome.style_guides DROP COLUMN IF EXISTS required_approvals;
--   ALTER TABLE apiome.style_guides DROP COLUMN IF EXISTS required_reviewer_role;
-- =====================================================================================

SET search_path TO apiome, public;

ALTER TABLE apiome.style_guides
    ADD COLUMN IF NOT EXISTS required_approvals INTEGER NOT NULL DEFAULT 0;

ALTER TABLE apiome.style_guides
    ADD COLUMN IF NOT EXISTS required_reviewer_role VARCHAR(64);

-- Bounds, added separately so a re-run against an already-migrated database is a no-op
-- rather than a duplicate-constraint error. The upper bound mirrors apiome-rest's
-- MAX_REVIEWERS (20): a round can never collect more approvals than it has reviewers, so a
-- higher requirement would be permanently unsatisfiable.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'style_guides_required_approvals_ck'
          AND conrelid = 'apiome.style_guides'::regclass
    ) THEN
        ALTER TABLE apiome.style_guides
            ADD CONSTRAINT style_guides_required_approvals_ck
            CHECK (required_approvals >= 0 AND required_approvals <= 20);
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'style_guides_required_reviewer_role_ck'
          AND conrelid = 'apiome.style_guides'::regclass
    ) THEN
        ALTER TABLE apiome.style_guides
            ADD CONSTRAINT style_guides_required_reviewer_role_ck
            CHECK (
                required_reviewer_role IS NULL
                OR char_length(btrim(required_reviewer_role)) BETWEEN 1 AND 64
            );
    END IF;
END
$$;

COMMENT ON COLUMN style_guides.required_approvals IS
    'Approvals a draft version needs on its current review round before it may be published; 0 disables the gate (COL-2.3, #4519)';

COMMENT ON COLUMN style_guides.required_reviewer_role IS
    'Optional roles.slug that at least one of those approvals must come from; NULL means any approver counts (COL-2.3, #4519)';
