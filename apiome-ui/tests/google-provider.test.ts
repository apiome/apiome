/**
 * Google Workspace NextAuth provider tests (OLO-9.2, #4985).
 *
 * The provider module is pure configuration plus the Workspace-domain gate, so every guarantee it
 * makes is directly assertable:
 *
 *   1. Env contract — GOOGLE_CLIENT_ID/SECRET are trimmed; GOOGLE_ISSUER points discovery at a mock
 *      (OLO-7.4) and defaults to the real Google issuer.
 *   2. Identity contract — provider id is `google` (the value the resolution engine's trust list and
 *      the external_auth_providers rows key on) and the profile maps the immutable `sub` claim to
 *      the NextAuth user id (→ account.providerAccountId → provider_user_id).
 *   3. Domain gate — with GOOGLE_WORKSPACE_DOMAIN set, the `hd` authorization param is sent and the
 *      `hd` claim is verified in the profile callback (case-insensitive), rejecting foreign/personal
 *      accounts; without it, any Google account is allowed.
 *   4. End to end — a mapped Google sign-in flows through the resolution engine, trusting Google's
 *      native `email_verified` claim and landing the identity as (google, sub).
 */
import { describe, test, expect } from '@jest/globals';

import {
  GOOGLE_PROVIDER_ID,
  assertGoogleHostedDomain,
  googleIssuerBaseUrl,
  googleProfile,
  googleProvider,
  googleWorkspaceDomain,
  hostedDomainMatches,
  type GoogleProfile,
} from '../lib/auth/google-provider';
import {
  AUTO_LINK_TRUSTED_PROVIDERS,
  AUTH_ERROR_CODES,
  resolveOAuthSignIn,
  type OAuthIdentityDetails,
  type ResolutionStore,
  type ResolutionUser,
} from '../lib/auth/account-resolution';
import { SUPPORTED_LOGIN_PROVIDERS } from '../lib/auth/credentials';

// helper.ts (transitively imported by credentials.ts) opens a pg pool at import time; mock it away.
jest.mock('../lib/db/db', () => ({ query: jest.fn() }));

const CONFIGURED_ENV = {
  GOOGLE_CLIENT_ID: 'client-id-123',
  GOOGLE_CLIENT_SECRET: 'secret-456',
};

/** next-auth stores built-in-provider user config under `options`; expose it for assertions. */
interface InspectableGoogle {
  id: string;
  checks?: string[];
  options?: {
    clientId?: string;
    clientSecret?: string;
    wellKnown?: string;
    authorization?: { params?: { scope?: string; hd?: string } };
  };
}

const inspect = (env: Record<string, string | undefined>) =>
  googleProvider(env) as unknown as InspectableGoogle;

// ---------------------------------------------------------------------------
// 1. Env contract
// ---------------------------------------------------------------------------

describe('env contract', () => {
  test('credentials are trimmed before use', () => {
    const provider = inspect({
      GOOGLE_CLIENT_ID: '  client-id-123  ',
      GOOGLE_CLIENT_SECRET: '  secret-456  ',
    });
    expect(provider.options?.clientId).toBe('client-id-123');
    expect(provider.options?.clientSecret).toBe('secret-456');
  });

  test('discovery defaults to the real Google issuer', () => {
    expect(googleIssuerBaseUrl({})).toBe('https://accounts.google.com');
    expect(inspect(CONFIGURED_ENV).options?.wellKnown).toBe(
      'https://accounts.google.com/.well-known/openid-configuration'
    );
  });

  test('GOOGLE_ISSUER points discovery at a mock issuer (OLO-7.4), trailing slash trimmed', () => {
    const provider = inspect({ ...CONFIGURED_ENV, GOOGLE_ISSUER: 'http://localhost:8091/google/' });
    expect(provider.options?.wellKnown).toBe(
      'http://localhost:8091/google/.well-known/openid-configuration'
    );
  });

  test('googleWorkspaceDomain reads GOOGLE_WORKSPACE_DOMAIN, blank counts as unset', () => {
    expect(googleWorkspaceDomain({})).toBeNull();
    expect(googleWorkspaceDomain({ GOOGLE_WORKSPACE_DOMAIN: '   ' })).toBeNull();
    expect(googleWorkspaceDomain({ GOOGLE_WORKSPACE_DOMAIN: '  corp.example.com  ' })).toBe(
      'corp.example.com'
    );
  });
});

// ---------------------------------------------------------------------------
// 2. Identity + protocol contract
// ---------------------------------------------------------------------------

describe('identity and protocol contract', () => {
  test('the provider id is `google` — the value every OLO seam keys on', () => {
    expect(GOOGLE_PROVIDER_ID).toBe('google');
    expect(inspect(CONFIGURED_ENV).id).toBe('google');
  });

  test('`google` is on the auto-link trust list and the signIn dispatch set', () => {
    expect(AUTO_LINK_TRUSTED_PROVIDERS.has(GOOGLE_PROVIDER_ID)).toBe(true);
    expect(SUPPORTED_LOGIN_PROVIDERS.has(GOOGLE_PROVIDER_ID)).toBe(true);
  });

  test('authorization-code + PKCE with state checks', () => {
    expect(inspect(CONFIGURED_ENV).checks).toEqual(['pkce', 'state']);
  });

  test('profile maps the immutable sub to the user id', () => {
    const user = googleProfile(
      {
        sub: 'google-sub-123',
        name: 'Ada Lovelace',
        email: 'ada@corp.example.com',
        picture: 'https://example.com/ada.png',
      },
      null
    );
    expect(user).toEqual({
      id: 'google-sub-123',
      name: 'Ada Lovelace',
      email: 'ada@corp.example.com',
      image: 'https://example.com/ada.png',
    });
  });

  test('a claim-free token maps to empty id and null fields (rejected later as incomplete)', () => {
    expect(googleProfile({}, null)).toEqual({ id: '', name: null, email: null, image: null });
  });
});

// ---------------------------------------------------------------------------
// 3. Workspace-domain gate
// ---------------------------------------------------------------------------

describe('hostedDomainMatches', () => {
  test('matches case-insensitively and ignores surrounding whitespace', () => {
    expect(hostedDomainMatches('corp.example.com', 'corp.example.com')).toBe(true);
    expect(hostedDomainMatches('  Corp.Example.COM ', 'corp.example.com')).toBe(true);
  });

  test('rejects a different domain, a missing claim, or a non-string claim', () => {
    expect(hostedDomainMatches('other.example.com', 'corp.example.com')).toBe(false);
    expect(hostedDomainMatches(undefined, 'corp.example.com')).toBe(false);
    expect(hostedDomainMatches(42, 'corp.example.com')).toBe(false);
  });
});

describe('assertGoogleHostedDomain', () => {
  test('is a no-op when no domain is configured (any account allowed)', () => {
    expect(() => assertGoogleHostedDomain({ hd: 'anything.com' }, null)).not.toThrow();
    expect(() => assertGoogleHostedDomain({}, null)).not.toThrow();
  });

  test('passes an account whose hd claim matches the configured domain', () => {
    expect(() =>
      assertGoogleHostedDomain({ hd: 'corp.example.com' }, 'corp.example.com')
    ).not.toThrow();
  });

  test('rejects a foreign-domain account', () => {
    expect(() =>
      assertGoogleHostedDomain({ hd: 'evil.example.com' }, 'corp.example.com')
    ).toThrow(/not a member of the 'corp.example.com'/);
  });

  test('rejects a personal account with no hd claim', () => {
    expect(() => assertGoogleHostedDomain({ email: 'me@gmail.com' }, 'corp.example.com')).toThrow(
      /not a member/
    );
  });
});

describe('authorization params carry the hd hint only when a domain is configured', () => {
  test('no hd param without a configured domain', () => {
    const params = inspect(CONFIGURED_ENV).options?.authorization?.params;
    expect(params?.scope).toBe('openid email profile');
    expect(params?.hd).toBeUndefined();
  });

  test('hd param present with a configured domain', () => {
    const params = inspect({
      ...CONFIGURED_ENV,
      GOOGLE_WORKSPACE_DOMAIN: 'corp.example.com',
    }).options?.authorization?.params;
    expect(params?.hd).toBe('corp.example.com');
  });

  test('the provider profile callback enforces the same gate it was built with', () => {
    // Build the provider with a domain, then exercise its bound profile callback.
    const provider = googleProvider({
      ...CONFIGURED_ENV,
      GOOGLE_WORKSPACE_DOMAIN: 'corp.example.com',
    }) as unknown as { options?: { profile?: (p: GoogleProfile) => unknown } };
    const profileFn = provider.options?.profile;
    expect(typeof profileFn).toBe('function');
    expect(() => profileFn!({ sub: 's', hd: 'corp.example.com' })).not.toThrow();
    expect(() => profileFn!({ sub: 's', hd: 'other.com' })).toThrow(/not a member/);
  });
});

// ---------------------------------------------------------------------------
// 4. End to end through the resolution engine
// ---------------------------------------------------------------------------

const ADA_USER: ResolutionUser = {
  id: 'user-ada',
  enabled: true,
  verified: true,
  email: 'ada@corp.example.com',
  name: 'Ada',
};

/** A legitimate Google token: Google natively asserts `email_verified`. */
const VERIFIED_TOKEN = {
  sub: 'google-sub-123',
  email: 'ada@corp.example.com',
  email_verified: true,
  name: 'Ada',
  hd: 'corp.example.com',
};

/** An unverified Google address: `email_verified` false → engine rejects as UNVERIFIED_EMAIL. */
const UNVERIFIED_TOKEN = {
  sub: 'google-sub-999',
  email: 'ada@corp.example.com',
  email_verified: false,
  name: 'Mallory',
};

/** In-memory store capturing what the engine persists. */
function makeStore(usersByEmail: Record<string, ResolutionUser>) {
  const linked: Array<{ userId: string; identity: OAuthIdentityDetails }> = [];
  const store: ResolutionStore = {
    async getIdentity() {
      return { found: false, userId: null };
    },
    async getUserById() {
      return null;
    },
    async getUserByEmail(email) {
      return usersByEmail[email] ?? null;
    },
    async linkIdentity(userId, identity) {
      linked.push({ userId, identity });
      return { success: true };
    },
    async recordIdentityLogin() {},
    async recordUserLogin() {},
    async createPendingSignup() {
      return { id: 'pending-1' };
    },
  };
  return { store, linked };
}

/**
 * Simulate the NextAuth wiring: the provider's profile() output becomes the payload user and
 * account.providerAccountId, while the raw token claims arrive as `profile`.
 */
function makeNextAuthPayload(claims: Record<string, unknown>, domain: string | null = null) {
  const mapped = googleProfile(claims, domain);
  return {
    user: { ...mapped },
    account: { provider: 'google', providerAccountId: mapped.id, access_token: 'tok' },
    profile: claims,
  };
}

describe('google provider → resolution engine, end to end', () => {
  test('a verified Google sign-in lands the identity as (google, sub) on the matching account', async () => {
    const { store, linked } = makeStore({ 'ada@corp.example.com': ADA_USER });
    const payload = makeNextAuthPayload(VERIFIED_TOKEN);

    const result = await resolveOAuthSignIn('google', payload, null, store);

    expect(result).toBe(true);
    expect(payload.user).toMatchObject({ id: ADA_USER.id });
    expect(linked).toHaveLength(1);
    expect(linked[0]).toMatchObject({
      userId: ADA_USER.id,
      identity: {
        provider: 'google',
        providerUserId: VERIFIED_TOKEN.sub,
        email: 'ada@corp.example.com',
        emailVerified: true,
      },
    });
  });

  test('an unverified Google address is rejected with the structured code', async () => {
    const { store, linked } = makeStore({ 'ada@corp.example.com': ADA_USER });

    const result = await resolveOAuthSignIn(
      'google',
      makeNextAuthPayload(UNVERIFIED_TOKEN),
      null,
      store
    );

    expect(result).toBe(`/login?error=${AUTH_ERROR_CODES.UNVERIFIED_EMAIL}`);
    expect(linked).toHaveLength(0);
  });

  test('a foreign-domain account never reaches the engine — the profile gate throws first', () => {
    // The domain gate runs inside profile(), i.e. before any signIn/resolution work.
    expect(() => makeNextAuthPayload({ sub: 's', hd: 'evil.com' }, 'corp.example.com')).toThrow(
      /not a member/
    );
  });
});
