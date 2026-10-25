-- Suite Access: a per-user switch for the Designer and Developer suites.
--
-- Before: the Build rail and the home launcher showed **Designer** to anyone entitled to the
-- `designer` or `paths` feature flag, and the free license bundle (V097) grants `designer`, so every
-- free account saw it. **Developer** had no gate at all. Both are beta / commercial products.
--
-- After: apiome-ui shows them only to a user whose `suite_access` is true. An administrator sets it
-- per user in the admin console (Users → Suite Access). No license, tenant override or feature-flag
-- override turns it on. Every existing account starts without it.
--
-- Rollback: ALTER TABLE apiome.users DROP COLUMN IF EXISTS suite_access;

SET search_path TO apiome, public;

ALTER TABLE apiome.users
  ADD COLUMN IF NOT EXISTS suite_access BOOLEAN NOT NULL DEFAULT false;

COMMENT ON COLUMN apiome.users.suite_access IS
  'Suite Access: whether the user sees the Designer and Developer suites. Set per user by an administrator; never granted by a license.';
