-- Release a deleted account's email address and sign-in identities, so the person can sign up again.
--
-- Before: deleting a user (admin console) only stamped `users.deleted_at` and `enabled = false`.
-- The row kept its email, its Better Auth `account` rows, its provider identities and its sessions.
-- Signing up again with that address failed with "We could not send the confirmation email":
-- apiome-ui's `createUser` saw the deleted row as an existing account. And because Better Auth looks
-- users up by email with no `deleted_at` filter, a second row with the same address would make
-- password sign-in pick either row.
--
-- After: deletion moves the address to `users.deleted_email` and gives the row a placeholder address
-- that can never receive mail (`deleted+<id>@deleted.invalid`, RFC 2606 `.invalid`). It also removes
-- the row's sessions, Better Auth accounts, provider identities and unused verification links. This
-- migration does the same for accounts deleted before it ran. apiome-ui's `deleteUser` does it for new
-- deletions, in one transaction.
--
-- Rollback notes: the column is additive, but the released rows are not restored. To put the
-- addresses back on deleted rows (only safe while no live account uses the same address):
--   UPDATE apiome.users SET email = deleted_email WHERE deleted_at IS NOT NULL AND deleted_email IS NOT NULL;
--   ALTER TABLE apiome.users DROP COLUMN IF EXISTS deleted_email;

SET search_path TO apiome, public;

ALTER TABLE apiome.users
  ADD COLUMN IF NOT EXISTS deleted_email VARCHAR(255);

COMMENT ON COLUMN apiome.users.deleted_email IS
  'The email address a deleted account had. Its email column holds a placeholder (deleted+<id>@deleted.invalid) so the address can be used again.';

-- Accounts deleted before this migration: release their addresses.
UPDATE apiome.users
   SET deleted_email = COALESCE(deleted_email, email),
       email = 'deleted+' || id::text || '@deleted.invalid',
       updated_at = CURRENT_TIMESTAMP
 WHERE deleted_at IS NOT NULL
   AND email <> 'deleted+' || id::text || '@deleted.invalid';

-- ...and the ways they could still sign in, or block someone else from signing up.
DELETE FROM apiome.session
 WHERE "userId" IN (SELECT id FROM apiome.users WHERE deleted_at IS NOT NULL);

DELETE FROM apiome.account
 WHERE "userId" IN (SELECT id FROM apiome.users WHERE deleted_at IS NOT NULL);

DELETE FROM apiome.external_auth_providers
 WHERE user_id IN (SELECT id FROM apiome.users WHERE deleted_at IS NOT NULL);

DELETE FROM apiome.email_verification_token
 WHERE user_id IN (SELECT id FROM apiome.users WHERE deleted_at IS NOT NULL);
