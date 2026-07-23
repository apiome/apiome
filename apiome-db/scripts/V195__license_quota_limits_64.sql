-- License plan quota limits: projects, published versions, AI functionality (#64).
--
-- The V097 license catalog stores every capacity limit as keys in the `seats` JSONB
-- ("so new limits can be added without schema changes"). Two of the three limits #64
-- asks the license to carry already have consumers:
--
--   * `max_projects`  — enforced on project creation by apiome-ui
--     (`lib/db/plan-entitlements.ts` via `entitlement-limits-from-license-seats.ts`).
--   * `max_versions`  — enforced on version publish by the same apiome-ui path.
--
-- …but the seeded Free/Paid/Sponsor tiers never populated those keys, so every plan
-- silently fell back to the Free defaults (1 project / 3 versions) regardless of tier —
-- a paid plan granted no more than a free one. And the third limit #64 asks for, an
-- **AI functionality** cap, existed nowhere.
--
-- This migration:
--   1. Populates the three quota keys on the seeded catalog tiers so each plan actually
--      differentiates what it grants. Free stays at the historical 1/3 defaults (no
--      change for existing free tenants); Paid and Sponsor grant more; Sponsor is
--      unlimited (negative = unlimited, matching the apiome-ui enforcement convention).
--   2. Introduces `max_ai_requests` — the AI-assistant request cap. Free = 0 (the Free
--      tier bundles no `ai_assistant` flag), Paid = a monthly allowance, Sponsor = -1.
--   3. Documents the full canonical key set on the `licenses.seats` column comment.
--
-- Fill-if-absent (`jsonb_build_object(...) || seats`): the built object supplies the
-- defaults and the existing `seats` wins on the right, so any key an operator already
-- set via the admin license manager is preserved — this migration never clobbers a
-- customised limit. Because the seeded tiers carry none of these keys today, they
-- receive exactly the per-tier values below.
--
-- Storage only, by design: like V097 (seat storage) preceded OLO-5.3 (seat
-- enforcement), this ships the AI cap as stored, readable, admin-editable data. There
-- is no AI-usage counter to meter against yet, so no enforcement path is added here.
SET search_path TO apiome, public;

-- ─── Free: unchanged historical defaults, AI disabled ────────────────────────
UPDATE apiome.licenses
SET    seats = jsonb_build_object(
                 'max_projects',    1,
                 'max_versions',    3,
                 'max_ai_requests', 0
               ) || seats,
       updated_at = CURRENT_TIMESTAMP
WHERE  name = 'Free' AND license_type = 'free';

-- ─── Paid: elevated project/version quotas, a monthly AI allowance ───────────
UPDATE apiome.licenses
SET    seats = jsonb_build_object(
                 'max_projects',    10,
                 'max_versions',    50,
                 'max_ai_requests', 1000
               ) || seats,
       updated_at = CURRENT_TIMESTAMP
WHERE  name = 'Paid' AND license_type = 'paid';

-- ─── Sponsor: unlimited on all three (-1) ────────────────────────────────────
UPDATE apiome.licenses
SET    seats = jsonb_build_object(
                 'max_projects',    -1,
                 'max_versions',    -1,
                 'max_ai_requests', -1
               ) || seats,
       updated_at = CURRENT_TIMESTAMP
WHERE  name = 'Sponsor' AND license_type = 'sponsor';

-- ─── Document the canonical seats keys ───────────────────────────────────────
COMMENT ON COLUMN apiome.licenses.seats IS
  'Capacity limits JSON. Canonical keys: max_tenants (int), max_users_per_tenant (int), '
  'max_projects (int), max_versions (int), max_ai_requests (int). For the quota keys '
  '(projects/versions/ai) a negative value means unlimited and a missing key falls back '
  'to the Free-tier default (1 project / 3 versions / 0 AI requests).';
