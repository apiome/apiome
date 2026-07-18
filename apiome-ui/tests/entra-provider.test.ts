/**
 * Microsoft Entra ID NextAuth provider tests (OLO-2.1, #4193).
 *
 * The provider module is pure configuration, so every guarantee it makes is directly assertable:
 *
 *   1. Env contract — AZURE_AD_CLIENT_ID/SECRET gate registration; AZURE_AD_TENANT defaults to
 *      `common` for multi-tenant sign-in.
 *   2. Identity contract — provider id is `azure` (the value the resolution engine's nOAuth
 *      gating and the external_auth_providers rows key on) and the profile maps the immutable
 *      `oid` claim to the NextAuth user id (→ account.providerAccountId → provider_user_id).
 *   3. Protocol contract — OIDC discovery per tenant, authorization-code + PKCE/state/nonce.
 *   4. End to end — a mapped Entra sign-in flows through the resolution engine with the OLO-1.4
 *      email rules applied, landing the identity as (azure, oid).
 */

import { describe, test, expect } from '@jest/globals';

import {
  ENTRA_ID_PROVIDER_ID,
  entraIdProfile,
  entraIdProvider,
  entraIdProviderIfConfigured,
  isEntraIdConfigured,
} from '../lib/auth/entra-provider';
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
  AZURE_AD_CLIENT_ID: 'client-id-123',
  AZURE_AD_CLIENT_SECRET: 'secret-456',
};

// ---------------------------------------------------------------------------
// 1. Env contract
// ---------------------------------------------------------------------------

describe('isEntraIdConfigured / entraIdProviderIfConfigured', () => {
  test('unset, blank, or partial credentials mean not configured', () => {
    expect(isEntraIdConfigured({})).toBe(false);
    expect(isEntraIdConfigured({ AZURE_AD_CLIENT_ID: 'id-only' })).toBe(false);
    expect(isEntraIdConfigured({ AZURE_AD_CLIENT_SECRET: 'secret-only' })).toBe(false);
    expect(
      isEntraIdConfigured({ AZURE_AD_CLIENT_ID: '   ', AZURE_AD_CLIENT_SECRET: 'x' })
    ).toBe(false);
  });

  test('both credentials present means configured', () => {
    expect(isEntraIdConfigured(CONFIGURED_ENV)).toBe(true);
  });

  test('an unconfigured deployment registers no provider at all', () => {
    expect(entraIdProviderIfConfigured({})).toEqual([]);
  });

  test('a configured deployment registers exactly the azure provider', () => {
    const providers = entraIdProviderIfConfigured(CONFIGURED_ENV);
    expect(providers).toHaveLength(1);
    expect(providers[0].id).toBe(ENTRA_ID_PROVIDER_ID);
  });

  test('credentials are trimmed before use', () => {
    const provider = entraIdProvider({
      AZURE_AD_CLIENT_ID: '  client-id-123  ',
      AZURE_AD_CLIENT_SECRET: '  secret-456  ',
    });
    expect(provider.clientId).toBe('client-id-123');
    expect(provider.clientSecret).toBe('secret-456');
  });
});

// ---------------------------------------------------------------------------
// 2. Identity contract
// ---------------------------------------------------------------------------

describe('provider identity contract', () => {
  test('the provider id is `azure` — the value every OLO seam keys on', () => {
    expect(ENTRA_ID_PROVIDER_ID).toBe('azure');
    expect(entraIdProvider(CONFIGURED_ENV).id).toBe('azure');
  });

  test('`azure` is on the auto-link trust list, so the OLO-1.4 gating actually applies', () => {
    expect(AUTO_LINK_TRUSTED_PROVIDERS.has(ENTRA_ID_PROVIDER_ID)).toBe(true);
  });

  test('the signIn dispatch supports `azure`', () => {
    expect(SUPPORTED_LOGIN_PROVIDERS.has(ENTRA_ID_PROVIDER_ID)).toBe(true);
  });

  test('profile maps the immutable oid — not sub — to the user id', () => {
    const user = entraIdProfile({
      oid: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
      sub: 'per-app-subject',
      name: 'Ada Lovelace',
      email: 'ada@corp.example.com',
    });
    expect(user).toEqual({
      id: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
      name: 'Ada Lovelace',
      email: 'ada@corp.example.com',
      image: null,
    });
  });

  test('profile falls back to sub only when the token carries no oid', () => {
    expect(entraIdProfile({ sub: 'per-app-subject' }).id).toBe('per-app-subject');
  });

  test('profile falls back to preferred_username for the display name', () => {
    expect(entraIdProfile({ oid: 'o-1', preferred_username: 'ada@corp.example.com' }).name).toBe(
      'ada@corp.example.com'
    );
  });

  test('a claim-free token maps to empty id and null fields (rejected later as incomplete)', () => {
    expect(entraIdProfile({})).toEqual({ id: '', name: null, email: null, image: null });
  });
});

// ---------------------------------------------------------------------------
// 3. Protocol contract
// ---------------------------------------------------------------------------

describe('protocol configuration', () => {
  test('discovery defaults to the multi-tenant `common` endpoint', () => {
    expect(entraIdProvider(CONFIGURED_ENV).wellKnown).toBe(
      'https://login.microsoftonline.com/common/v2.0/.well-known/openid-configuration?appid=client-id-123'
    );
  });

  test('AZURE_AD_TENANT scopes discovery to that tenant', () => {
    const provider = entraIdProvider({ ...CONFIGURED_ENV, AZURE_AD_TENANT: 'corp.example.com' });
    expect(provider.wellKnown).toBe(
      'https://login.microsoftonline.com/corp.example.com/v2.0/.well-known/openid-configuration?appid=client-id-123'
    );
  });

  test('AZURE_AD_AUTHORITY_BASE_URL points discovery at a mock authority (OLO-7.4)', () => {
    const provider = entraIdProvider({
      ...CONFIGURED_ENV,
      AZURE_AD_AUTHORITY_BASE_URL: 'http://localhost:8091/azure/',
      AZURE_AD_TENANT: 'mock-tenant',
    });
    expect(provider.wellKnown).toBe(
      'http://localhost:8091/azure/mock-tenant/v2.0/.well-known/openid-configuration?appid=client-id-123'
    );
  });

  test('authorization-code + PKCE with state and nonce checks, reading the id token', () => {
    const provider = entraIdProvider(CONFIGURED_ENV);
    expect(provider.type).toBe('oauth');
    expect(provider.idToken).toBe(true);
    expect(provider.checks).toEqual(expect.arrayContaining(['pkce', 'state', 'nonce']));
    expect((provider.authorization as { params: { scope: string } }).params.scope).toBe(
      'openid profile email offline_access'
    );
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

/** Legitimate multi-tenant token: xms_edov proves the email (see OLO-1.4 tests). */
const LEGIT_TOKEN = {
  oid: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
  sub: 'per-app-subject',
  email: 'ada@corp.example.com',
  upn: 'ada@corp.example.com',
  name: 'Ada',
  xms_edov: true,
};

/** nOAuth forgery: attacker-controlled email, no verification evidence. */
const FORGED_TOKEN = {
  oid: '11111111-2222-3333-4444-555555555555',
  sub: 'attacker-subject',
  email: 'ada@corp.example.com',
  upn: 'attacker@attackertenant.onmicrosoft.com',
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
function makeNextAuthPayload(claims: Record<string, unknown>) {
  const mapped = entraIdProfile(claims);
  return {
    user: { ...mapped },
    account: { provider: 'azure', providerAccountId: mapped.id, access_token: 'tok' },
    profile: claims,
  };
}

describe('entra provider → resolution engine, end to end', () => {
  test('a legitimate sign-in lands the identity as (azure, oid) on the matching account', async () => {
    const { store, linked } = makeStore({ 'ada@corp.example.com': ADA_USER });
    const payload = makeNextAuthPayload(LEGIT_TOKEN);

    const result = await resolveOAuthSignIn('azure', payload, null, store);

    expect(result).toBe(true);
    expect(payload.user).toMatchObject({ id: ADA_USER.id });
    expect(linked).toHaveLength(1);
    expect(linked[0]).toMatchObject({
      userId: ADA_USER.id,
      identity: {
        provider: 'azure',
        providerUserId: LEGIT_TOKEN.oid, // oid, never sub
        email: 'ada@corp.example.com',
        emailVerified: true,
      },
    });
  });

  test('the same wiring rejects a forged nOAuth token with the structured code', async () => {
    const { store, linked } = makeStore({ 'ada@corp.example.com': ADA_USER });

    const result = await resolveOAuthSignIn('azure', makeNextAuthPayload(FORGED_TOKEN), null, store);

    expect(result).toBe(`/login?error=${AUTH_ERROR_CODES.UNVERIFIED_EMAIL}`);
    expect(linked).toHaveLength(0);
  });
});
