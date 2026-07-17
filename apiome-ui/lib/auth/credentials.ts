import * as helper from '../db/helper';
import { upsertOauthSignupPending, consumeAuthOneTimeCode } from '../db/oauth-signup';
import {
  checkLoginRateLimit,
  recordLoginFailure,
  recordLoginSuccess,
  credentialsRateLimitKey,
} from './login-rate-limit';
import {
  resolveOAuthSignIn,
  resolveOAuthEmailVerified,
  resolveEntraEmailVerified,
  type OAuthSignInResult,
  type ResolutionStore,
  type ResolutionUser,
} from './account-resolution';

const bcrypt = require('bcrypt');

// Re-exported for existing consumers/tests; the implementation lives with the resolution engine.
export { resolveOAuthEmailVerified, resolveEntraEmailVerified };

export interface ICredentials {
  email?: string;
  password?: string;
  oneTimeCode?: string;
}

/** Map a users row onto the account facts the resolution engine decides over. */
const toResolutionUser = (row: any): ResolutionUser => ({
  id: row.id,
  enabled: !!row.enabled,
  verified: !!row.verified,
  email: row.email ?? null,
  name: row.name ?? null,
});

/**
 * Production persistence wiring for the account-resolution engine (OLO-1.3). Each operation
 * delegates to the existing db helpers; the engine itself stays free of database imports so the
 * policy is testable in isolation.
 */
const resolutionStore: ResolutionStore = {
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

/**
 * Shared OAuth sign-in entry point for every provider's NextAuth signIn callback (OLO-1.3).
 *
 * Consumes the link/signup intent cookies, then runs the account-resolution engine: known
 * identity → sign in; verified email match → auto-link + sign in; verified email, no account →
 * onboarding; unverified email → structured rejection.
 *
 * @param provider Provider slug as reported by NextAuth ('github' | 'gitlab' | …).
 * @param payload The NextAuth signIn callback payload; mutated with the resolved user on success.
 * @returns `true` to admit the sign-in or a redirect path (error, signup wizard, or the
 *   linked-accounts page for explicit link flows).
 */
export const oauthProviderSignIn = async (
  provider: string,
  payload: any
): Promise<OAuthSignInResult> => {
  // Both intent cookies are one-shot: read them (which clears them) before resolving. The signup
  // intent no longer alters the policy — new verified users are always routed to onboarding, and
  // existing accounts are signed in rather than duplicated — but the cookie must still be consumed.
  const linkIntent = await checkLinkingIntent();
  await checkSignupIntent();

  const linkToUserId =
    linkIntent && linkIntent.provider === provider && linkIntent.userId ? linkIntent.userId : null;

  try {
    return await resolveOAuthSignIn(provider, payload, linkToUserId, resolutionStore);
  } catch (error) {
    console.error(`[oauthProviderSignIn] ${provider} resolution failed:`, error);
    return false;
  }
};

/**
 * Check if this is a linking flow (user already logged in and clicking "Link" button)
 * Note: This function will be called from the OAuth callback
 */
export const checkLinkingIntent = async () => {
  try {
    const { cookies } = await import('next/headers');
    const cookieStore = await cookies();
    const linkIntent = cookieStore.get('oauth_link_intent');

    if (linkIntent && linkIntent.value) {
      try {
        const intent = JSON.parse(linkIntent.value);
        if (Date.now() - intent.timestamp < 600000) {
          cookieStore.delete('oauth_link_intent');
          return intent;
        }
        cookieStore.delete('oauth_link_intent');
      } catch {
        cookieStore.delete('oauth_link_intent');
      }
    }
  } catch {
    // Cookie store unavailable; treat as no intent
  }

  return null;
};

/**
 * Check if the user started OAuth from "Create account" (self-signup) mode.
 */
export const checkSignupIntent = async () => {
  try {
    const { cookies } = await import('next/headers');
    const cookieStore = await cookies();
    const raw = cookieStore.get('oauth_signup_intent');

    if (raw && raw.value) {
      try {
        const intent = JSON.parse(raw.value);
        if (Date.now() - intent.timestamp < 600000) {
          cookieStore.delete('oauth_signup_intent');
          return intent as { provider: string; timestamp: number };
        }
        cookieStore.delete('oauth_signup_intent');
      } catch {
        cookieStore.delete('oauth_signup_intent');
      }
    }
  } catch {
    // Cookie store unavailable
  }

  return null;
};

/*
 * Authorization steps:
 * 1. User is retrieved by e-mail address.
 * 2. Comparison is checked against user password and stored password using bcrypt.
 * 3. If the user login succeeds, the record is returned without the password field.
 * 4. Failure returns a null, which the next-auth `authorize()` handler will interpret as an invalid account.
 *
 * One-time codes (after OAuth signup completion) are also accepted.
 */
export const credentialsAuthorize = async (credentials: ICredentials) => {
  if (credentials.oneTimeCode?.trim()) {
    const consumed = await consumeAuthOneTimeCode(credentials.oneTimeCode.trim());
    if (!consumed) {
      return null;
    }
    const userResults = await helper.getUserById(consumed.userId);
    if (userResults.rowCount === 0) {
      return null;
    }
    const userResult = userResults.rows[0];
    delete userResult.password;
    return {
      ...userResult,
      pending_tenant_id: consumed.tenantId,
    };
  }

  const password = credentials.password;
  const email = credentials.email;
  if (!email || !password) {
    return null;
  }

  // Brute-force protection: refuse the attempt (without touching the DB or hashing)
  // once this account has accumulated too many recent failures. See login-rate-limit.ts.
  const rateLimitKey = credentialsRateLimitKey(email);
  if (rateLimitKey && checkLoginRateLimit(rateLimitKey).blocked) {
    console.warn(`[credentialsAuthorize] Login temporarily locked for ${email} (too many failed attempts)`);
    return null;
  }

  const results = await helper.getUserByEmail(email);

  if (results.rowCount > 0) {
    const userResult = results.rows[0];
    const hashPassword = userResult.password;

    if (userResult.password && bcrypt.compareSync(password, hashPassword)) {
      delete userResult.password;
      if (rateLimitKey) {
        recordLoginSuccess(rateLimitKey);
      }
      return userResult;
    }
  }

  // No user, no stored password, or a bad password — all count as a failed attempt.
  if (rateLimitKey) {
    recordLoginFailure(rateLimitKey);
  }
  return null;
};

/*
 * Sign-in Steps:
 * 1. User must exist.
 *    If user is null, return 'User account not found'
 * 2. Enabled must be true.
 *    If not enabled, return 'Your account is currently disabled'
 * 3. Verified must be true.
 *    If not verified, return 'You have not yet verified your account e-mail address'
 *
 * If all passes, true is returned.
 */
export const credentialsSignIn = async (payload: any) => {
  const user = payload.user;

  if (!user.enabled) {
    return '/login?error=Your account is currently disabled';
  }

  if (!user.verified) {
    return '/login?error=You have not yet verified your account e-mail address';
  }

  if (user.id) {
    void helper.updateUserLastLoginAt(user.id).catch((error: any) => {
      console.error('[credentialsSignIn] Failed to update last login timestamp:', error);
    });
  }

  return true;
};

