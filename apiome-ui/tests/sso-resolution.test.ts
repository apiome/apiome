/**
 * Enterprise SSO sign-ins through the account-resolution engine — EID-1.1 (#5011).
 *
 * `lib/auth/sso-resolution.ts` runs the engine in Better Auth's database hooks on the SSO callback
 * routes. Every dependency is injected (an in-memory store, a fake id-token verifier, captured audit
 * rows), and each case runs inside the same per-request scopes the handler sets up, so the published
 * redirect is asserted exactly as the browser would receive it.
 *
 * Pinned: routes other than SSO callbacks are untouched; an email outside the provider's verified
 * domains, an OIDC identity whose email the IdP did not verify, a bad id token and a closed sign-up
 * policy are all refused with a stable code, an `auth_events` failure row and no account; a new user
 * goes to the onboarding wizard with no stray user row; an existing account is auto-linked through
 * the engine; and plugin-native failures map onto stable `sso-*` codes.
 */

jest.mock('better-auth/api', () => {
  class APIError extends Error {
    status: string;
    body: Record<string, unknown>;
    constructor(status: string, body: Record<string, unknown> = {}) {
      super(String(body.message ?? status));
      this.status = status;
      this.body = body;
    }
  }
  return { APIError, createAuthMiddleware: (handler: unknown) => handler };
});
jest.mock('jose', () => ({ createRemoteJWKSet: jest.fn(), jwtVerify: jest.fn() }));
jest.mock('../lib/auth/resolution-store', () => ({ resolutionStore: {} }));
jest.mock('../lib/auth/oauth-link-intent', () => ({ checkLinkingIntent: async () => null }));
jest.mock('../lib/db/db', () => ({ query: jest.fn() }));

import { describe, expect, test } from '@jest/globals';

import type { ResolutionStore, ResolutionUser } from '../lib/auth/account-resolution';
import { getOauthRedirectOverride, runWithOauthRedirectOverride } from '../lib/auth/better-auth-oauth-providers';
import type { ResolvedSsoProvider, ResolvedSsoProviders } from '../lib/auth/sso-provider-resolver';
import {
  emailInProviderDomains,
  isSsoCallbackPath,
  mapPluginError,
  runWithSsoRequest,
  ssoAccountCreateBefore,
  ssoArtifactBeforeHandler,
  ssoCallbackAfterHandler,
  ssoProviderIdFromContext,
  ssoSessionCreateBefore,
  ssoUserCreateBefore,
  type SsoAuthEvent,
  type SsoResolutionDeps,
} from '../lib/auth/sso-resolution';
import { signupPolicyFromEnv } from '../lib/auth/signup-policy';

/* ── Fixtures ─────────────────────────────────────────────────────────────────────────────── */

const OIDC: ResolvedSsoProvider = {
  id: 'p-oidc',
  slug: 'acme',
  pluginProviderId: 'sso-acme',
  identityKind: 'sso:acme',
  protocol: 'oidc',
  displayName: 'Acme',
  issuer: 'https://idp.acme.test',
  tenantId: null,
  domains: ['acme.test'],
  oidcConfig: { client_id: 'apiome', jwks_uri: 'https://idp.acme.test/certs' },
  samlConfig: null,
  clientSecret: 'secret',
  spPrivateKey: null,
};

const SAML: ResolvedSsoProvider = {
  ...OIDC,
  id: 'p-saml',
  slug: 'acme-saml',
  pluginProviderId: 'sso-acme-saml',
  identityKind: 'sso:acme-saml',
  protocol: 'saml',
  oidcConfig: null,
  samlConfig: { idp_entity_id: 'https://idp.acme.test/saml', email_source: 'nameid' },
  clientSecret: null,
};

const RESOLVED: ResolvedSsoProviders = { providers: [OIDC, SAML], fingerprint: 'f' };

const OIDC_CALLBACK = { path: '/sso/callback/:providerId', params: { providerId: 'sso-acme' } };
const SAML_ACS = { path: '/sso/saml2/sp/acs/:providerId', params: { providerId: 'sso-acme-saml' } };

function user(overrides: Partial<ResolutionUser> = {}): ResolutionUser {
  return { id: 'u-1', enabled: true, verified: true, email: 'ada@acme.test', name: 'Ada', ...overrides };
}

/** An in-memory store, with every call recorded. */
function makeStore(init: { users?: ResolutionUser[]; identities?: Record<string, string>; policy?: string } = {}) {
  const users = new Map((init.users ?? []).map((u) => [u.id, u]));
  const identities = new Map(Object.entries(init.identities ?? {}));
  const calls = { linkIdentity: [] as unknown[][], pending: [] as unknown[][] };
  const store: ResolutionStore = {
    async getIdentity(provider, providerUserId) {
      const userId = identities.get(`${provider}|${providerUserId}`);
      return { found: Boolean(userId), userId: userId ?? null };
    },
    async getUserById(id) {
      return users.get(id) ?? null;
    },
    async getUserByEmail(email) {
      return [...users.values()].find((u) => u.email === email) ?? null;
    },
    async linkIdentity(userId, details) {
      calls.linkIdentity.push([userId, details]);
      identities.set(`${details.provider}|${details.providerUserId}`, userId);
      return { success: true };
    },
    async recordIdentityLogin() {},
    async recordUserLogin() {},
    async getSignupPolicy() {
      return signupPolicyFromEnv(init.policy === 'closed' ? { AUTH_SIGNUP_DISABLED: 'true' } : {});
    },
    async createPendingSignup(...args) {
      calls.pending.push(args);
      return { id: 'pending-1' };
    },
  };
  return { store, calls, identities };
}

function makeDeps(store: ResolutionStore, over: Partial<SsoResolutionDeps> = {}) {
  const events: SsoAuthEvent[] = [];
  const discarded: [string, string][] = [];
  const deps: SsoResolutionDeps = {
    store,
    verifyIdToken: async () => ({ email: 'ada@acme.test', email_verified: true }),
    discardNewUser: async (id, marker) => {
      discarded.push([id, marker]);
    },
    accountIdFor: async () => 'sub-123',
    recordEvent: async (event) => {
      events.push(event);
    },
    ...over,
  };
  return { deps, events, discarded };
}

/** Run `fn` inside the handler's two request scopes; report the redirect and any throw. */
async function inRequest<T>(fn: () => Promise<T>) {
  let result: T | undefined;
  let thrown: unknown = null;
  let redirect: string | null = null;
  await runWithOauthRedirectOverride(() =>
    runWithSsoRequest(RESOLVED, async () => {
      try {
        result = await fn();
      } catch (error) {
        thrown = error;
      }
      redirect = getOauthRedirectOverride();
    })
  );
  return { result, thrown: thrown as { body?: { code?: string } } | null, redirect: redirect as string | null };
}

/* ── Paths ────────────────────────────────────────────────────────────────────────────────── */

describe('SSO callback routes', () => {
  test('recognises the OIDC callback and both SAML routes, as templates or concrete paths', () => {
    expect(isSsoCallbackPath('/sso/callback/:providerId')).toBe(true);
    expect(isSsoCallbackPath('/sso/saml2/sp/acs/sso-acme')).toBe(true);
    expect(isSsoCallbackPath('/sso/saml2/callback/sso-acme')).toBe(true);
    expect(isSsoCallbackPath('/sign-in/sso')).toBe(false);
    expect(isSsoCallbackPath('/oauth2/callback/okta')).toBe(false);
    expect(isSsoCallbackPath(undefined)).toBe(false);
  });

  test('reads the provider id from the params, or from a concrete path', () => {
    expect(ssoProviderIdFromContext(OIDC_CALLBACK)).toBe('sso-acme');
    expect(ssoProviderIdFromContext({ path: '/sso/saml2/sp/acs/sso-acme-saml' })).toBe('sso-acme-saml');
    expect(ssoProviderIdFromContext({ path: '/sso/callback/okta' })).toBeNull(); // not an SSO id
    expect(ssoProviderIdFromContext({ path: '/callback/github', params: { providerId: 'sso-acme' } })).toBeNull();
    expect(ssoProviderIdFromContext(undefined)).toBeNull();
  });

  test('an email is covered only by an exact verified domain', () => {
    expect(emailInProviderDomains('Ada@ACME.test', OIDC)).toBe(true);
    expect(emailInProviderDomains('ada@sub.acme.test', OIDC)).toBe(false);
    expect(emailInProviderDomains('ada@acme.test.evil', OIDC)).toBe(false);
    expect(emailInProviderDomains(null, OIDC)).toBe(false);
  });
});

/* ── Non-SSO requests are untouched ───────────────────────────────────────────────────────── */

describe('outside SSO callbacks', () => {
  test('every hook is a no-op', async () => {
    const { store, calls } = makeStore();
    const { deps, events } = makeDeps(store);
    const ctx = { path: '/oauth2/callback/:providerId', params: { providerId: 'okta' } };
    const outcome = await inRequest(async () => [
      await ssoUserCreateBefore({ email: 'x@y.test' }, ctx, deps),
      await ssoAccountCreateBefore({ userId: 'u' }, ctx, deps),
      await ssoSessionCreateBefore({ userId: 'u' }, ctx, deps),
      await ssoUserCreateBefore({ email: 'x@y.test' }, undefined, deps),
    ]);
    expect(outcome.thrown).toBeNull();
    expect(outcome.result).toEqual([undefined, undefined, undefined, undefined]);
    expect(outcome.redirect).toBeNull();
    expect(events).toEqual([]);
    expect(calls.pending).toEqual([]);
  });
});

/* ── A new user ───────────────────────────────────────────────────────────────────────────── */

describe('a brand-new SSO user', () => {
  test('goes to the onboarding wizard, leaving no user row behind', async () => {
    const { store, calls } = makeStore();
    const { deps, events, discarded } = makeDeps(store);
    let marker = '';

    const outcome = await inRequest(async () => {
      const created = await ssoUserCreateBefore({ email: 'Ada@Acme.test', name: '', emailVerified: true }, OIDC_CALLBACK, deps);
      expect(created?.data.email).toBe('ada@acme.test');
      expect(created?.data.emailVerified).toBe(true);
      expect(created?.data.name).toBe('ada'); // NOT NULL column: the local part stands in
      marker = created?.data.password as string;
      expect(marker).toMatch(/^sso-pending-[0-9a-f]{48}$/);
      await ssoAccountCreateBefore(
        { userId: 'tmp-user', accountId: 'sub-123', providerId: 'sso-acme', idToken: 'id.token.jwt' },
        OIDC_CALLBACK,
        deps
      );
    });

    expect(outcome.thrown?.body?.code).toBe('sso-signup-pending');
    expect(outcome.redirect).toBe('/signup/oauth?token=pending-1');
    expect(calls.pending).toHaveLength(1);
    expect(calls.pending[0].slice(0, 3)).toEqual(['sso:acme', 'sub-123', 'ada@acme.test']);
    expect(discarded).toEqual([['tmp-user', marker]]);
    expect(events).toEqual([
      expect.objectContaining({ event_type: 'sign_up', outcome: 'success', provider: 'sso:acme', user_label: 'ada@acme.test' }),
    ]);
  });

  test('a SAML user needs no id token', async () => {
    const { store, calls } = makeStore();
    const verifyIdToken = jest.fn(async () => ({}));
    const { deps } = makeDeps(store, { verifyIdToken });
    const outcome = await inRequest(async () => {
      await ssoUserCreateBefore({ email: 'ada@acme.test', name: 'Ada', emailVerified: false }, SAML_ACS, deps);
      await ssoAccountCreateBefore({ userId: 'tmp', accountId: 'nameid-1' }, SAML_ACS, deps);
    });
    expect(outcome.redirect).toBe('/signup/oauth?token=pending-1');
    expect(calls.pending[0][0]).toBe('sso:acme-saml');
    expect(verifyIdToken).not.toHaveBeenCalled();
  });

  test.each([
    ['an email outside the verified domains', { email: 'ada@other.test', emailVerified: true }, 'sso-email-domain-mismatch'],
    ['an OIDC email the IdP did not verify', { email: 'ada@acme.test', emailVerified: false }, 'unverified-email'],
  ])('is refused for %s, before any row is written', async (_label, data, code) => {
    const { store } = makeStore();
    const { deps, events } = makeDeps(store);
    const outcome = await inRequest(() => ssoUserCreateBefore({ name: 'Ada', ...data }, OIDC_CALLBACK, deps));
    expect(outcome.thrown?.body?.code).toBe(code);
    expect(outcome.redirect).toBe(`/login?error=${code}`);
    expect(events).toEqual([expect.objectContaining({ outcome: 'failure', error_code: code, provider: 'sso:acme' })]);
  });

  test('is refused when the sign-up policy is closed', async () => {
    const { store } = makeStore({ policy: 'closed' });
    const { deps } = makeDeps(store);
    const outcome = await inRequest(() =>
      ssoUserCreateBefore({ email: 'ada@acme.test', emailVerified: true }, OIDC_CALLBACK, deps)
    );
    expect(outcome.thrown?.body?.code).toBe('signup-disabled');
  });

  test('a bad id token is refused, and the throwaway user row removed', async () => {
    const { store, calls } = makeStore();
    const { deps, discarded } = makeDeps(store, {
      verifyIdToken: async () => {
        throw new Error('signature');
      },
    });
    const outcome = await inRequest(async () => {
      const created = await ssoUserCreateBefore({ email: 'ada@acme.test', emailVerified: true }, OIDC_CALLBACK, deps);
      await ssoAccountCreateBefore({ userId: 'tmp', accountId: 'sub', idToken: 'bad' }, OIDC_CALLBACK, deps);
      return created;
    });
    expect(outcome.thrown?.body?.code).toBe('sso-token-invalid');
    expect(outcome.redirect).toBe('/login?error=sso-token-invalid');
    expect(discarded).toHaveLength(1);
    expect(calls.pending).toEqual([]);
  });

  test('an unknown provider is refused', async () => {
    const { store } = makeStore();
    const { deps } = makeDeps(store);
    const outcome = await inRequest(() =>
      ssoUserCreateBefore({ email: 'ada@acme.test' }, { path: '/sso/callback/sso-gone', params: { providerId: 'sso-gone' } }, deps)
    );
    expect(outcome.thrown?.body?.code).toBe('sso-provider-not-found');
  });
});

/* ── Linking an existing account ──────────────────────────────────────────────────────────── */

describe('an existing account signing in through SSO for the first time', () => {
  test('checks the id token, then the engine auto-links it at session time', async () => {
    const { store, calls } = makeStore({ users: [user()] });
    const { deps, events } = makeDeps(store);
    const outcome = await inRequest(async () => {
      await ssoAccountCreateBefore({ userId: 'u-1', accountId: 'sub-123', idToken: 'jwt' }, OIDC_CALLBACK, deps);
      await ssoSessionCreateBefore({ userId: 'u-1' }, OIDC_CALLBACK, deps);
    });
    expect(outcome.thrown).toBeNull();
    expect(outcome.redirect).toBeNull();
    expect(calls.linkIdentity).toHaveLength(1);
    expect(calls.linkIdentity[0][0]).toBe('u-1');
    expect(calls.linkIdentity[0][1]).toEqual(expect.objectContaining({ provider: 'sso:acme', providerUserId: 'sub-123' }));
    expect(events).toEqual([expect.objectContaining({ event_type: 'sign_in', outcome: 'success', user_id: 'u-1' })]);
  });

  test.each([
    ['the IdP did not verify the email', { email: 'ada@acme.test', email_verified: false }, 'unverified-email'],
    ['the token names another email', { email: 'eve@acme.test', email_verified: true }, 'sso-token-invalid'],
  ])('is refused when %s — never linked', async (_label, claims, code) => {
    const { store, calls } = makeStore({ users: [user()] });
    const { deps } = makeDeps(store, { verifyIdToken: async () => claims });
    const outcome = await inRequest(() =>
      ssoAccountCreateBefore({ userId: 'u-1', accountId: 'sub-123', idToken: 'jwt' }, OIDC_CALLBACK, deps)
    );
    expect(outcome.thrown?.body?.code).toBe(code);
    expect(calls.linkIdentity).toEqual([]);
  });

  test('an OIDC link with no id token is refused', async () => {
    const { store } = makeStore({ users: [user()] });
    const { deps } = makeDeps(store);
    const outcome = await inRequest(() => ssoAccountCreateBefore({ userId: 'u-1', accountId: 'sub' }, OIDC_CALLBACK, deps));
    expect(outcome.thrown?.body?.code).toBe('sso-token-invalid');
  });

  test('an account whose email is outside the provider’s domains is refused', async () => {
    const { store } = makeStore({ users: [user({ email: 'ada@other.test' })] });
    const { deps } = makeDeps(store);
    const outcome = await inRequest(() =>
      ssoAccountCreateBefore({ userId: 'u-1', accountId: 'sub', idToken: 'jwt' }, OIDC_CALLBACK, deps)
    );
    expect(outcome.thrown?.body?.code).toBe('sso-email-domain-mismatch');
  });
});

/* ── Known identities ─────────────────────────────────────────────────────────────────────── */

describe('a known SSO identity', () => {
  test('signs in', async () => {
    const { store, calls } = makeStore({ users: [user()], identities: { 'sso:acme|sub-123': 'u-1' } });
    const { deps } = makeDeps(store);
    const outcome = await inRequest(() => ssoSessionCreateBefore({ userId: 'u-1' }, OIDC_CALLBACK, deps));
    expect(outcome.thrown).toBeNull();
    expect(calls.linkIdentity).toEqual([]);
  });

  test.each([
    ['a disabled account', user({ enabled: false }), 'account-disabled'],
    ['an unverified account', user({ verified: false }), 'account-not-verified'],
  ])('is refused for %s', async (_label, u, code) => {
    const { store } = makeStore({ users: [u], identities: { 'sso:acme|sub-123': 'u-1' } });
    const { deps, events } = makeDeps(store);
    const outcome = await inRequest(() => ssoSessionCreateBefore({ userId: 'u-1' }, OIDC_CALLBACK, deps));
    expect(outcome.thrown?.body?.code).toBe(code);
    expect(outcome.redirect).toBe(`/login?error=${code}`);
    expect(events[0]).toEqual(expect.objectContaining({ outcome: 'failure', error_code: code }));
  });

  test('bound to another user is refused rather than signing that user in', async () => {
    const { store } = makeStore({
      users: [user(), user({ id: 'u-2', email: 'eve@acme.test' })],
      identities: { 'sso:acme|sub-123': 'u-2' },
    });
    const { deps } = makeDeps(store);
    const outcome = await inRequest(() => ssoSessionCreateBefore({ userId: 'u-1' }, OIDC_CALLBACK, deps));
    expect(outcome.thrown?.body?.code).toBe('identity-linked-elsewhere');
  });

  test('with no Better Auth account row is refused', async () => {
    const { store } = makeStore({ users: [user()] });
    const { deps } = makeDeps(store, { accountIdFor: async () => null });
    const outcome = await inRequest(() => ssoSessionCreateBefore({ userId: 'u-1' }, OIDC_CALLBACK, deps));
    expect(outcome.thrown?.body?.code).toBe('OAuthProfileIncomplete');
  });
});

/* ── Plugin-native failures ───────────────────────────────────────────────────────────────── */

describe('plugin-native failures', () => {
  test.each([
    ['replay_detected', null, 'saml', 'sso-assertion-replayed'],
    ['invalid_state', null, 'oidc', 'sso-state-invalid'],
    ['discovery_failed', 'issuer_mismatch', 'oidc', 'sso-discovery-failed'],
    ['account_not_linked', null, 'oidc', 'sso-account-not-linked'],
    ['invalid_provider', 'token_not_verified', 'oidc', 'sso-token-invalid'],
    ['invalid_provider', 'provider not found', 'oidc', 'sso-provider-not-found'],
    ['invalid_saml_response', 'Invalid signature', 'saml', 'sso-assertion-invalid'],
    ['invalid_saml_response', 'unsupported binding', 'saml', 'sso-binding-unsupported'],
    ['something_else', null, null, 'sign-in-failed'],
  ] as const)('%s (%s) on %s → %s', (error, description, protocol, code) => {
    expect(mapPluginError(error, description, protocol)).toBe(code);
  });

  test('the after hook retargets the plugin’s error redirect and records it', async () => {
    const { store } = makeStore();
    const { deps, events } = makeDeps(store);
    const headers = new Headers({ location: '/login?error=replay_detected&error_description=used' });
    const outcome = await inRequest(() =>
      ssoCallbackAfterHandler({ ...SAML_ACS, context: { returned: { headers } } }, deps)
    );
    expect(outcome.redirect).toBe('/login?error=sso-assertion-replayed');
    expect(events).toEqual([
      expect.objectContaining({ outcome: 'failure', provider: 'sso:acme-saml', error_code: 'sso-assertion-replayed' }),
    ]);
  });

  test('the after hook leaves successes, other routes and decided outcomes alone', async () => {
    const { store } = makeStore();
    const { deps, events } = makeDeps(store);
    const ok = new Headers({ location: '/ade' });
    const failed = new Headers({ location: '/login?error=invalid_state' });
    const outcome = await inRequest(async () => {
      await ssoCallbackAfterHandler({ ...OIDC_CALLBACK, context: { returned: { headers: ok } } }, deps);
      await ssoCallbackAfterHandler({ path: '/callback/github', context: { returned: { headers: failed } } }, deps);
      await ssoCallbackAfterHandler({ ...OIDC_CALLBACK, context: { returned: { headers: failed } } }, deps, () => true);
    });
    expect(outcome.redirect).toBeNull();
    expect(events).toEqual([]);
  });

  test('an HTTP-Artifact response is refused with sso-binding-unsupported', async () => {
    const { store } = makeStore();
    const { deps, events } = makeDeps(store);
    const redirect = jest.fn((url: string) => ({ redirectedTo: url }));
    const outcome = await inRequest(() =>
      ssoArtifactBeforeHandler({ ...SAML_ACS, body: { SAMLart: 'AAQ…' }, redirect }, deps)
    );
    expect(redirect).toHaveBeenCalledWith('/login?error=sso-binding-unsupported');
    expect(outcome.thrown).toEqual({ redirectedTo: '/login?error=sso-binding-unsupported' });
    expect(events[0]).toEqual(expect.objectContaining({ error_code: 'sso-binding-unsupported' }));
  });

  test('a POSTed SAMLResponse passes the artifact check', async () => {
    const { store } = makeStore();
    const { deps } = makeDeps(store);
    const outcome = await inRequest(() => ssoArtifactBeforeHandler({ ...SAML_ACS, body: { SAMLResponse: 'PD94…' } }, deps));
    expect(outcome.thrown).toBeNull();
  });
});
