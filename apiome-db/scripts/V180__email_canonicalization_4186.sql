-- Email canonicalization + case-insensitive uniqueness (OLO-1.1, #4186).
--
-- `apiome.users.email` (V001) carried a plain `VARCHAR(255) ... UNIQUE` constraint. That is a
-- *byte-exact* uniqueness guarantee, so `Ada@Example.com` and `ada@example.com` were two distinct
-- accounts — the exact failure the OAuth/login epic forbids ("one email address controls a
-- person's access"). This migration makes duplicate-cased signups impossible at the DB level and
-- normalizes every existing address to its canonical `lower(trim(...))` form.
--
-- Existing case-collision duplicates are **surfaced, never silently merged**. For each set of
-- active rows that collapse to the same normalized address we:
--   1. Record every member in `apiome.email_canonicalization_conflicts` (the audit table an
--      operator works from — see docs/EMAIL_CANONICALIZATION_RUNBOOK.md).
--   2. Keep the earliest-created row as the canonical account (`kept_active`).
--   3. Quarantine the rest by soft-deleting them (`deleted_at`, `enabled = false`) so no data is
--      lost and the unique index can build. Their rows and audit trail remain for manual merge.
-- No account data is combined — merging is an operator decision, driven by the runbook.
--
-- Uniqueness is enforced with a *functional partial* unique index on `lower(email)` restricted to
-- live rows (`deleted_at IS NULL`), mirroring the existing `idx_users_email` predicate. The old
-- byte-exact table constraint is dropped: it was both too strict (blocked reusing a soft-deleted
-- address) and case-blind. The functional index also serves the `lower(email) = lower($1)` lookups
-- the REST/CLI layers issue, so the now-redundant `idx_users_email` is dropped alongside it.
SET search_path TO apiome, public;

-- Audit trail of every address involved in a case-collision. Deliberately carries no foreign key
-- to `users`: it must outlive a hard-delete of any row it references so the merge history is never
-- lost. `action_taken` is 'kept_active' for the surviving canonical row, 'quarantined' otherwise.
CREATE TABLE IF NOT EXISTS apiome.email_canonicalization_conflicts (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id           UUID NOT NULL,
    original_email    VARCHAR(255) NOT NULL,   -- address exactly as stored before normalization
    normalized_email  VARCHAR(255) NOT NULL,   -- lower(trim(original_email))
    is_canonical      BOOLEAN NOT NULL,        -- true for the single row kept active per group
    action_taken      VARCHAR(32) NOT NULL,    -- 'kept_active' | 'quarantined'
    detected_at       TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE apiome.email_canonicalization_conflicts IS
    'Case-collision duplicates surfaced by V180. One row per user in each colliding set; the '
    'canonical row is kept active and the rest are quarantined (soft-deleted) for manual merge.';

-- Groups are resolved by normalized address; keep this fast for the runbook queries.
CREATE INDEX IF NOT EXISTS idx_email_conflicts_normalized
    ON apiome.email_canonicalization_conflicts(normalized_email);

-- Drop the byte-exact uniqueness so normalization cannot collide with it. Postgres named the
-- V001 `UNIQUE` constraint `users_email_key`; guard the drop so re-runs / hand-built schemas are
-- tolerated.
ALTER TABLE apiome.users DROP CONSTRAINT IF EXISTS users_email_key;

-- Surface every colliding active row into the audit table. The earliest-created row (ties broken
-- by id) is canonical; the rest are marked for quarantine.
WITH conflict_groups AS (
    SELECT lower(trim(email)) AS norm
    FROM apiome.users
    WHERE deleted_at IS NULL
    GROUP BY lower(trim(email))
    HAVING count(*) > 1
),
ranked AS (
    SELECT u.id,
           u.email,
           lower(trim(u.email)) AS norm,
           row_number() OVER (
               PARTITION BY lower(trim(u.email))
               ORDER BY u.created_at ASC, u.id ASC
           ) AS rn
    FROM apiome.users u
    JOIN conflict_groups g ON lower(trim(u.email)) = g.norm
    WHERE u.deleted_at IS NULL
)
INSERT INTO apiome.email_canonicalization_conflicts
    (user_id, original_email, normalized_email, is_canonical, action_taken)
SELECT id,
       email,
       norm,
       (rn = 1),
       CASE WHEN rn = 1 THEN 'kept_active' ELSE 'quarantined' END
FROM ranked;

-- Quarantine the non-canonical duplicates: soft-delete + disable. No account data is merged; the
-- rows survive for an operator to reconcile per the runbook.
UPDATE apiome.users u
SET deleted_at = CURRENT_TIMESTAMP,
    enabled = false,
    updated_at = CURRENT_TIMESTAMP
FROM apiome.email_canonicalization_conflicts c
WHERE u.id = c.user_id
  AND c.action_taken = 'quarantined'
  AND u.deleted_at IS NULL;

-- Normalize every remaining address (active and historical) to its canonical form. After the
-- quarantine step no two *active* rows share a normalized address, so this cannot collide with the
-- unique index built below.
UPDATE apiome.users
SET email = lower(trim(email)),
    updated_at = CURRENT_TIMESTAMP
WHERE email <> lower(trim(email));

-- Enforce case-insensitive uniqueness for live accounts. Duplicate-cased signups are now
-- impossible at the DB level.
CREATE UNIQUE INDEX IF NOT EXISTS uq_users_email_lower
    ON apiome.users (lower(email))
    WHERE deleted_at IS NULL;

-- Retire the now-redundant case-sensitive lookup index; the functional index above covers
-- `lower(email) = ...` reads.
DROP INDEX IF EXISTS apiome.idx_users_email;
