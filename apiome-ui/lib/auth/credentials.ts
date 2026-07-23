import * as helper from '../db/helper';
import { consumeAuthOneTimeCode } from '../db/oauth-signup';
import {
  checkLoginRateLimit,
  recordLoginFailure,
  recordLoginSuccess,
  credentialsRateLimitKey,
  credentialsIpRateLimitKey,
  CREDENTIALS_IP_MAX_ATTEMPTS,
} from './login-rate-limit';
import {
  AUTH_ERROR_CODES,
  LINKABLE_PROVIDERS,
  loginErrorRedirect,
  resolveOAuthSignIn,
  resolveOAuthEmailVerified,
  resolveEntraEmailVerified,
  type OAuthSignInResult,
} from './account-resolution';
import { resolutionStore } from './resolution-store';

const bcrypt = require('bcrypt');

/**
 * A fixed, valid bcrypt hash (cost 10 — the cost every password write in this codebase uses)
 * that no real password equals. The credentials path compares against it whenever the email has
 * no account or no usable password, so a failed sign-in always performs exactly one bcrypt
 * verification. Without this, the hash only ran when the account existed, and the extra latency
 * let an attacker enumerate valid emails by response time even within the rate-limit budget
 * (OLO-7.3 threat-model fix). The plaintext is irrelevant — the value must never match a login.
 */
const DECOY_PASSWORD_HASH = '$2b$10$LRiE9uVVzAnnUJNQ5ewIXu11h7QPAED4M3Wo3D6uXa3KnELjifewe';

// Re-exported for existing consumers/tests; the implementation lives with the resolution engine.
export { resolveOAuthEmailVerified, resolveEntraEmailVerified };

export interface ICredentials {
  email?: string;
  password?: string;
  oneTimeCode?: string;
}

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
 *
 * Brute-force protection (RC1-0.3 + OLO-7.1): failures are counted per account
 * (`cred:<email>`) and per client IP (`cred-ip:<ip>`, looser cap) — either lock
 * refuses the attempt before any DB or bcrypt work. One-time-code guesses count
 * against the IP lock too.
 */
export const credentialsAuthorize = async (
  credentials: ICredentials,
  clientIp?: string | null
) => {
  const ipKey = credentialsIpRateLimitKey(clientIp);
  if (ipKey && checkLoginRateLimit(ipKey, Date.now(), CREDENTIALS_IP_MAX_ATTEMPTS).blocked) {
    console.warn('[credentialsAuthorize] Login temporarily locked for this client (too many failed attempts)');
    return null;
  }

  if (credentials.oneTimeCode?.trim()) {
    const consumed = await consumeAuthOneTimeCode(credentials.oneTimeCode.trim());
    if (!consumed) {
      // A bad one-time code is a guessable secret: count it against the IP lock.
      if (ipKey) {
        recordLoginFailure(ipKey, Date.now(), CREDENTIALS_IP_MAX_ATTEMPTS);
      }
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

  // Refuse the attempt (without touching the DB or hashing) once this account has
  // accumulated too many recent failures. See login-rate-limit.ts.
  const rateLimitKey = credentialsRateLimitKey(email);
  if (rateLimitKey && checkLoginRateLimit(rateLimitKey).blocked) {
    console.warn(`[credentialsAuthorize] Login temporarily locked for ${email} (too many failed attempts)`);
    return null;
  }

  const results = await helper.getUserByEmail(email);
  const userResult = results.rowCount > 0 ? results.rows[0] : null;
  const storedHash =
    userResult && typeof userResult.password === 'string' && userResult.password.length > 0
      ? userResult.password
      : DECOY_PASSWORD_HASH;

  // Always run one bcrypt comparison — against the decoy hash when there is no account or no
  // usable password — so a miss costs the same as a wrong password and the response time cannot
  // be used to enumerate valid emails (OLO-7.3). The decoy hash never matches, so a missing
  // account still falls through to the failure path below.
  const passwordMatches = bcrypt.compareSync(password, storedHash);

  if (userResult && userResult.password && passwordMatches) {
    delete userResult.password;
    if (rateLimitKey) {
      recordLoginSuccess(rateLimitKey);
    }
    if (ipKey) {
      recordLoginSuccess(ipKey);
    }
    return userResult;
  }

  // No user, no stored password, or a bad password — all count as a failed attempt
  // against both the account lock and the (looser) per-IP lock.
  if (rateLimitKey) {
    recordLoginFailure(rateLimitKey);
  }
  if (ipKey) {
    recordLoginFailure(ipKey, Date.now(), CREDENTIALS_IP_MAX_ATTEMPTS);
  }
  return null;
};

/*
 * Sign-in Steps:
 * 1. Enabled must be true.
 *    If not enabled, redirect with the stable `account-disabled` code.
 * 2. Verified must be true.
 *    If not verified, redirect with the stable `account-not-verified` code.
 *
 * Rejections carry the structured auth error contract codes (OLO-1.5) so the login page renders
 * the same guidance whether the failure came from credentials or an OAuth provider.
 *
 * If all passes, true is returned.
 */
export const credentialsSignIn = async (payload: any) => {
  const user = payload.user;

  if (!user.enabled) {
    return loginErrorRedirect(AUTH_ERROR_CODES.ACCOUNT_DISABLED);
  }

  if (!user.verified) {
    return loginErrorRedirect(AUTH_ERROR_CODES.ACCOUNT_NOT_VERIFIED);
  }

  if (user.id) {
    void helper.updateUserLastLoginAt(user.id).catch((error: any) => {
      console.error('[credentialsSignIn] Failed to update last login timestamp:', error);
    });
  }

  return true;
};

/**
 * Providers the NextAuth signIn callback knows how to dispatch: `credentials` plus every linkable
 * OAuth provider (`LINKABLE_PROVIDERS` — the single provider vocabulary, OLO-2.2). `azure` is
 * Microsoft Entra ID (OLO-2.1); its NextAuth provider is only registered when the deployment
 * configures it (`entra-provider.ts`), so an azure callback can only ever arrive on a configured
 * deployment.
 */
export const SUPPORTED_LOGIN_PROVIDERS: ReadonlySet<string> = new Set([
  'credentials',
  ...LINKABLE_PROVIDERS,
]);

/**
 * Dispatch a NextAuth signIn callback to the matching provider flow (OLO-1.5).
 *
 * Credentials sign-ins run the account gates; every supported OAuth provider flows through the
 * account-resolution engine; anything else — a provider this deployment has not configured — is
 * refused with the stable `provider-not-configured` code.
 *
 * @param provider Provider slug as reported by NextAuth (`payload.account.provider`).
 * @param payload The NextAuth signIn callback payload.
 * @returns `true` to admit the sign-in or a redirect path carrying the outcome.
 */
export const signInForProvider = async (
  provider: string,
  payload: any
): Promise<OAuthSignInResult> => {
  if (provider === 'credentials') {
    return credentialsSignIn(payload);
  }

  if (SUPPORTED_LOGIN_PROVIDERS.has(provider)) {
    return oauthProviderSignIn(provider, payload);
  }

  return loginErrorRedirect(AUTH_ERROR_CODES.PROVIDER_NOT_CONFIGURED);
};

