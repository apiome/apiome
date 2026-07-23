/**
 * Production persistence wiring for the account-resolution engine (OLO-1.3, #4188).
 *
 * The pure policy (`account-resolution.ts`) is deliberately free of database imports so the full
 * matrix is testable in isolation; the concrete `ResolutionStore` — the side that actually reads
 * and writes the identity/user rows — lives here. Both sign-in engines share this one store: the
 * NextAuth path (`credentials.ts`) and the Better Auth adapter
 * (`better-auth-account-resolution.ts`, OLO-10.6). Keeping a single store means the two engines can
 * never drift on how an identity is looked up, linked, or stamped — the migration re-homes *where*
 * the store is invoked from (a Better Auth sign-in/callback hook), not the store's SQL.
 *
 * Every operation delegates to the existing `lib/db` helpers, which own the OLO-1.2 uniqueness
 * constraints and the structured failure codes.
 */

import * as helper from '../db/helper';
import { upsertOauthSignupPending } from '../db/oauth-signup';
import type { ResolutionStore, ResolutionUser } from './account-resolution';

/**
 * Map a `users` row onto the account facts the resolution engine decides over.
 *
 * @param row A row from `apiome.users` (as returned by the `lib/db` helpers).
 * @returns The `ResolutionUser` the pure policy reads (id + the enabled/verified gates + display
 *   fields), with the boolean gates coerced so a NULL/undefined column never reads as truthy.
 */
export const toResolutionUser = (row: any): ResolutionUser => ({
  id: row.id,
  enabled: !!row.enabled,
  verified: !!row.verified,
  email: row.email ?? null,
  name: row.name ?? null,
});

/**
 * The production account-resolution store shared by both sign-in engines.
 *
 * Each method is a thin adapter over a `lib/db` helper; the engine gathers these facts before the
 * pure decision runs, then executes the decision's effects (link / stamp / pending-signup) through
 * the same store. `linkIdentity` surfaces the helper's structured `code` so the engine's
 * "admit an auto-link only when the bind actually persisted" invariant (OLO-1.2) is preserved.
 */
export const resolutionStore: ResolutionStore = {
  async getIdentity(provider, providerUserId) {
    const parsed = JSON.parse(await helper.getLinkedAccountByProvider(provider, providerUserId));
    return { found: !!parsed.found, userId: parsed.account?.user_id ?? null };
  },

  async getUserById(userId) {
    const results = await helper.getUserById(userId);
    return results.rowCount > 0 ? toResolutionUser(results.rows[0]) : null;
  },

  async getUserByEmail(email) {
    const results = await helper.getUserByEmail(email);
    return results.rowCount > 0 ? toResolutionUser(results.rows[0]) : null;
  },

  async linkIdentity(userId, identity) {
    const parsed = JSON.parse(
      await helper.linkExternalAccount(
        userId,
        identity.provider,
        identity.providerUserId,
        identity.email as string,
        identity.username,
        identity.accessToken,
        identity.refreshToken,
        identity.tokenExpiresAt,
        identity.profileData,
        identity.emailVerified
      )
    );
    return { success: !!parsed.success, code: parsed.code };
  },

  async recordIdentityLogin(provider, providerUserId, email, emailVerified) {
    await helper.updateLinkedAccountLastLogin(provider, providerUserId, email, emailVerified);
  },

  async recordUserLogin(userId) {
    await helper.updateUserLastLoginAt(userId);
  },

  async createPendingSignup(provider, providerUserId, email, account, profile) {
    return upsertOauthSignupPending(provider, providerUserId, email, account, profile);
  },
};
