/**
 * Entra ID nOAuth hardening tests (OLO-1.4, #4189).
 *
 * `resolveEntraEmailVerified` decides whether an Entra ID (azure) token proved its email claim.
 * Entra's `email` claim is attacker-controlled in multi-tenant app registrations (the published
 * nOAuth account-takeover pattern), so the resolver must accept only real evidence — `xms_edov`,
 * `email_verified`, or email == member UPN — and fail closed on everything else.
 *
 * Part 1 exercises the claim matrix directly, including forged-token fixtures modelled on the
 * nOAuth attack. Part 2 drives the full engine (`resolveOAuthSignIn`) with the same fixtures to
 * prove forged sign-ins are rejected end to end while legitimate ones auto-link.
 */

import { describe, test, expect } from '@jest/globals';

import {
  resolveEntraEmailVerified,
  resolveOAuthSignIn,
  AUTH_ERROR_CODES,
  type OAuthIdentityDetails,
  type ResolutionStore,
  type ResolutionUser,
} from '../lib/auth/account-resolution';

// ---------------------------------------------------------------------------
// Token fixtures
// ---------------------------------------------------------------------------

/**
 * The nOAuth forgery: an attacker admins their own tenant and sets the victim's address on the
 * mutable `mail` attribute. The token is otherwise legitimate — only the email is a lie. No
 * verification evidence is present, and the attacker's UPN cannot carry the victim's domain.
 */
const FORGED_NOAUTH_TOKEN = {
  sub: 'attacker-sub',
  oid: '11111111-2222-3333-4444-555555555555',
  tid: 'attacker-tenant-id',
  email: 'victim@corp.example.com',
  upn: 'attacker@attackertenant.onmicrosoft.com',
  name: 'Mallory',
};

/** Forgery variant: a guest (B2B) account whose UPN embeds the victim address as `#EXT#`. */
const FORGED_GUEST_TOKEN = {
  sub: 'guest-sub',
  oid: '66666666-7777-8888-9999-000000000000',
  tid: 'attacker-tenant-id',
  email: 'victim@corp.example.com',
  upn: 'victim_corp.example.com#EXT#@attackertenant.onmicrosoft.com',
};

/** Legitimate sign-in from an app registration with the `xms_edov` optional claim enabled. */
const LEGIT_EDOV_TOKEN = {
  sub: 'member-sub',
  oid: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
  tid: 'corp-tenant-id',
  email: 'Ada@Corp.example.com',
  upn: 'ada@corp.example.com',
  xms_edov: true,
};

// ---------------------------------------------------------------------------
// Part 1 — claim matrix
// ---------------------------------------------------------------------------

describe('resolveEntraEmailVerified — forged tokens are rejected', () => {
  test('nOAuth forgery (arbitrary email, no evidence) is unverified', () => {
    expect(resolveEntraEmailVerified(FORGED_NOAUTH_TOKEN, {})).toBe(false);
  });

  test('guest UPN embedding the victim address (#EXT#) proves nothing', () => {
    expect(resolveEntraEmailVerified(FORGED_GUEST_TOKEN, {})).toBe(false);
  });

  test('an explicitly-false xms_edov vetoes every other rule, including a true email_verified', () => {
    expect(
      resolveEntraEmailVerified(
        { email: 'ada@corp.example.com', email_verified: true, xms_edov: false },
        {}
      )
    ).toBe(false);
    expect(
      resolveEntraEmailVerified(
        { email: 'ada@corp.example.com', upn: 'ada@corp.example.com', xms_edov: false },
        {}
      )
    ).toBe(false);
    expect(
      resolveEntraEmailVerified({ email: 'ada@corp.example.com', xms_edov: 'false' }, {})
    ).toBe(false);
  });

  test('an explicitly-false email_verified vetoes the UPN rule', () => {
    expect(
      resolveEntraEmailVerified(
        { email: 'ada@corp.example.com', upn: 'ada@corp.example.com', email_verified: false },
        {}
      )
    ).toBe(false);
  });

  test('positive claims only attest the token email, never a different address in use', () => {
    // The token verified its own email, but the sign-in is about to use another address.
    expect(
      resolveEntraEmailVerified(LEGIT_EDOV_TOKEN, {}, 'someone-else@corp.example.com')
    ).toBe(false);
    // An explicit null email-in-use means "no usable address" — always unverified.
    expect(resolveEntraEmailVerified(LEGIT_EDOV_TOKEN, {}, null)).toBe(false);
  });

  test('unrecognized claim values and missing email fail closed', () => {
    expect(resolveEntraEmailVerified({ email: 'a@b.co', xms_edov: 'yes' }, {})).toBe(false);
    expect(resolveEntraEmailVerified({ email: 'a@b.co', email_verified: 'verified' }, {})).toBe(false);
    expect(resolveEntraEmailVerified({ xms_edov: true }, {})).toBe(false); // evidence, no email
    expect(resolveEntraEmailVerified(null, null)).toBe(false);
    expect(resolveEntraEmailVerified({}, {})).toBe(false);
  });

  test('a non-email-shaped or non-string UPN never matches', () => {
    expect(
      resolveEntraEmailVerified({ email: 'ada@localhost', upn: 'ada@localhost' }, {})
    ).toBe(false); // no dot in domain — not an email-shaped UPN
    expect(resolveEntraEmailVerified({ email: 'ada@corp.example.com', upn: 42 }, {})).toBe(false);
  });
});

describe('resolveEntraEmailVerified — legitimate evidence is accepted', () => {
  test('xms_edov true (boolean, "true", 1, "1") verifies the token email', () => {
    expect(resolveEntraEmailVerified(LEGIT_EDOV_TOKEN, {})).toBe(true);
    expect(resolveEntraEmailVerified({ email: 'a@b.co', xms_edov: 'true' }, {})).toBe(true);
    expect(resolveEntraEmailVerified({ email: 'a@b.co', xms_edov: 1 }, {})).toBe(true);
    expect(resolveEntraEmailVerified({ email: 'a@b.co', xms_edov: '1' }, {})).toBe(true);
  });

  test('email_verified true verifies the token email', () => {
    expect(resolveEntraEmailVerified({ email: 'a@b.co', email_verified: true }, {})).toBe(true);
    expect(resolveEntraEmailVerified({ email: 'a@b.co', email_verified: 'true' }, {})).toBe(true);
  });

  test('claims are read from the account object when absent from the profile', () => {
    expect(resolveEntraEmailVerified({ email: 'a@b.co' }, { xms_edov: true })).toBe(true);
    expect(resolveEntraEmailVerified({ email: 'a@b.co' }, { email_verified: true })).toBe(true);
  });

  test('email == member UPN verifies (case-insensitively), with no boolean claims at all', () => {
    expect(
      resolveEntraEmailVerified(
        { email: 'Ada@Corp.example.com', upn: 'ada@CORP.example.com' },
        {}
      )
    ).toBe(true);
  });

  test('the email-in-use parameter verifies when it matches the attested address', () => {
    expect(resolveEntraEmailVerified(LEGIT_EDOV_TOKEN, {}, 'ada@corp.example.com')).toBe(true);
    // UPN rule attests the address in use even when the token carries no email claim.
    expect(
      resolveEntraEmailVerified({ upn: 'ada@corp.example.com' }, {}, 'Ada@corp.example.com')
    ).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Part 2 — end-to-end through the resolution engine
// ---------------------------------------------------------------------------

const VICTIM_USER: ResolutionUser = {
  id: 'user-victim',
  enabled: true,
  verified: true,
  email: 'victim@corp.example.com',
  name: 'Victim',
};

const ADA_USER: ResolutionUser = {
  id: 'user-ada',
  enabled: true,
  verified: true,
  email: 'ada@corp.example.com',
  name: 'Ada',
};

/** Minimal fake store: no known identities; users looked up by canonical email. */
function makeStore(usersByEmail: Record<string, ResolutionUser>) {
  const calls = {
    linkIdentity: [] as Array<{ userId: string; identity: OAuthIdentityDetails }>,
    createPendingSignup: [] as Array<{ provider: string; providerUserId: string; email: string }>,
  };
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
      calls.linkIdentity.push({ userId, identity });
      return { success: true };
    },
    async recordIdentityLogin() {},
    async recordUserLogin() {},
    async createPendingSignup(provider, providerUserId, email) {
      calls.createPendingSignup.push({ provider, providerUserId, email });
      return { id: 'pending-1' };
    },
  };
  return { store, calls };
}

const makeAzurePayload = (profile: Record<string, unknown>) => ({
  user: { email: profile.email ?? null, name: profile.name ?? null },
  account: { providerAccountId: profile.oid ?? 'azure-oid', access_token: 'tok' },
  profile,
});

describe('resolveOAuthSignIn — azure goes through the nOAuth rules', () => {
  test('a forged nOAuth token never auto-links to the victim account', async () => {
    const { store, calls } = makeStore({ 'victim@corp.example.com': VICTIM_USER });

    const result = await resolveOAuthSignIn(
      'azure',
      makeAzurePayload(FORGED_NOAUTH_TOKEN),
      null,
      store
    );

    expect(result).toBe(`/login?error=${AUTH_ERROR_CODES.UNVERIFIED_EMAIL}`);
    expect(calls.linkIdentity).toHaveLength(0);
    expect(calls.createPendingSignup).toHaveLength(0);
  });

  test('a forged guest-UPN token is rejected the same way', async () => {
    const { store, calls } = makeStore({ 'victim@corp.example.com': VICTIM_USER });

    const result = await resolveOAuthSignIn(
      'azure',
      makeAzurePayload(FORGED_GUEST_TOKEN),
      null,
      store
    );

    expect(result).toBe(`/login?error=${AUTH_ERROR_CODES.UNVERIFIED_EMAIL}`);
    expect(calls.linkIdentity).toHaveLength(0);
  });

  test('a legitimate token with xms_edov auto-links to the matching account', async () => {
    const { store, calls } = makeStore({ 'ada@corp.example.com': ADA_USER });
    const payload = makeAzurePayload(LEGIT_EDOV_TOKEN);

    const result = await resolveOAuthSignIn('azure', payload, null, store);

    expect(result).toBe(true);
    expect(payload.user).toMatchObject({ id: ADA_USER.id });
    expect(calls.linkIdentity).toHaveLength(1);
    expect(calls.linkIdentity[0]).toMatchObject({
      userId: ADA_USER.id,
      identity: { provider: 'azure', email: 'ada@corp.example.com', emailVerified: true },
    });
  });

  test('azure ignores a bare email_verified=true lookalike only when contradicted (xms_edov=false)', async () => {
    const { store, calls } = makeStore({ 'ada@corp.example.com': ADA_USER });

    const result = await resolveOAuthSignIn(
      'azure',
      makeAzurePayload({
        oid: 'contradiction-oid',
        email: 'ada@corp.example.com',
        email_verified: true,
        xms_edov: false,
      }),
      null,
      store
    );

    expect(result).toBe(`/login?error=${AUTH_ERROR_CODES.UNVERIFIED_EMAIL}`);
    expect(calls.linkIdentity).toHaveLength(0);
  });

  test('the generic provider path is unchanged: gitlab email_verified=true still auto-links', async () => {
    const { store, calls } = makeStore({ 'ada@corp.example.com': ADA_USER });

    const result = await resolveOAuthSignIn(
      'gitlab',
      {
        user: { email: 'ada@corp.example.com' },
        account: { providerAccountId: 'gl-1' },
        profile: { email: 'ada@corp.example.com', email_verified: true },
      },
      null,
      store
    );

    expect(result).toBe(true);
    expect(calls.linkIdentity).toHaveLength(1);
  });
});
