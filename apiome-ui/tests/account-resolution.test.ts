/**
 * Account-resolution & auto-link engine tests (OLO-1.3, #4188).
 *
 * Part 1 property-tests the pure policy over the full matrix of
 * {new/known identity} × {new/known email} × {verified/unverified} × {signed-in link},
 * asserting the ticket's two acceptance invariants:
 *   - a second account can never be created for an existing email, and
 *   - unverified emails never authenticate.
 *
 * Part 2 exercises the orchestrator (`resolveOAuthSignIn`) against a fake store: what gets
 * persisted, how the NextAuth payload is mutated, and which redirects are produced.
 *
 * The engine module is intentionally free of database imports, so no db mocking is needed here.
 */

import { describe, test, expect } from '@jest/globals';
import {
  AUTH_ERROR_CODES,
  AUTO_LINK_TRUSTED_PROVIDERS,
  canonicalizeEmail,
  resolveAccountDecision,
  resolveOAuthSignIn,
  type ResolutionInput,
  type ResolutionStore,
  type ResolutionUser,
} from '../lib/auth/account-resolution';

const OK_USER: ResolutionUser = { id: 'user-ok', enabled: true, verified: true, email: 'ada@example.com', name: 'Ada' };
const DISABLED_USER: ResolutionUser = { id: 'user-disabled', enabled: false, verified: true };
const UNVERIFIED_USER: ResolutionUser = { id: 'user-unverified', enabled: true, verified: false };

// ---------------------------------------------------------------------------
// Part 1 — pure policy
// ---------------------------------------------------------------------------

describe('resolveAccountDecision — property matrix', () => {
  type IdentityKind = 'none' | 'known' | 'known-disabled' | 'known-unverified' | 'dangling';
  type EmailUserKind = 'none' | 'match' | 'match-disabled' | 'match-unverified';

  const identityOf = (kind: IdentityKind): ResolutionInput['identity'] => {
    switch (kind) {
      case 'none': return { found: false, user: null };
      case 'known': return { found: true, user: OK_USER };
      case 'known-disabled': return { found: true, user: DISABLED_USER };
      case 'known-unverified': return { found: true, user: UNVERIFIED_USER };
      case 'dangling': return { found: true, user: null };
    }
  };

  const emailUserOf = (kind: EmailUserKind): ResolutionUser | null => {
    switch (kind) {
      case 'none': return null;
      case 'match': return OK_USER;
      case 'match-disabled': return DISABLED_USER;
      case 'match-unverified': return UNVERIFIED_USER;
    }
  };

  /** Every combination the policy can face for a trusted provider. */
  const matrix: Array<{ input: ResolutionInput; label: string }> = [];
  for (const identityKind of ['none', 'known', 'known-disabled', 'known-unverified', 'dangling'] as IdentityKind[]) {
    for (const email of [null, 'ada@example.com']) {
      for (const emailUserKind of ['none', 'match', 'match-disabled', 'match-unverified'] as EmailUserKind[]) {
        // A user can only match an email that exists.
        if (email === null && emailUserKind !== 'none') continue;
        for (const emailVerified of [false, true]) {
          for (const linkToUserId of [null, 'session-user']) {
            matrix.push({
              label: `identity=${identityKind} email=${email} emailUser=${emailUserKind} verified=${emailVerified} link=${linkToUserId}`,
              input: {
                provider: 'github',
                providerUserId: 'prov-123',
                email,
                emailVerified,
                linkToUserId,
                identity: identityOf(identityKind),
                emailUser: emailUserOf(emailUserKind),
              },
            });
          }
        }
      }
    }
  }

  test('matrix covers the full state space', () => {
    // 5 identities × (1 no-email + 4 email-user kinds) × 2 verified × 2 link intents.
    expect(matrix.length).toBe(5 * 5 * 2 * 2);
  });

  test('invariant: a second account is never created for an existing email', () => {
    for (const { input, label } of matrix) {
      const decision = resolveAccountDecision(input);
      if (decision.action === 'signup') {
        expect({ label, emailUser: input.emailUser }).toEqual({ label, emailUser: null });
      }
    }
  });

  test('invariant: unverified emails never authenticate (nor sign up)', () => {
    for (const { input, label } of matrix) {
      if (input.linkToUserId || input.identity.found || input.emailVerified) continue;
      const decision = resolveAccountDecision(input);
      expect({ label, action: decision.action }).toEqual({ label, action: 'reject' });
      const expectedCode = input.email
        ? AUTH_ERROR_CODES.UNVERIFIED_EMAIL
        : AUTH_ERROR_CODES.EMAIL_REQUIRED;
      expect({ label, code: (decision as any).code }).toEqual({ label, code: expectedCode });
    }
  });

  test('invariant: disabled or unverified accounts are never admitted', () => {
    for (const { input, label } of matrix) {
      const decision = resolveAccountDecision(input);
      if (decision.action === 'sign-in' || decision.action === 'auto-link') {
        expect({ label, enabled: decision.user.enabled, verified: decision.user.verified })
          .toEqual({ label, enabled: true, verified: true });
      }
    }
  });

  test('invariant: explicit link intent always attaches to the session user', () => {
    for (const { input, label } of matrix) {
      if (!input.linkToUserId) continue;
      const decision = resolveAccountDecision(input);
      expect({ label, decision }).toEqual({
        label,
        decision: { action: 'link-to-session', userId: 'session-user' },
      });
    }
  });

  test('invariant: a known healthy identity signs in its user regardless of email state', () => {
    for (const { input, label } of matrix) {
      if (input.linkToUserId || !input.identity.found || input.identity.user !== OK_USER) continue;
      const decision = resolveAccountDecision(input);
      expect({ label, decision }).toEqual({
        label,
        decision: { action: 'sign-in', user: OK_USER },
      });
    }
  });

  test('invariant: auto-link happens exactly when a verified email matches a healthy account', () => {
    for (const { input, label } of matrix) {
      const decision = resolveAccountDecision(input);
      const shouldAutoLink =
        !input.linkToUserId &&
        !input.identity.found &&
        input.emailVerified &&
        input.emailUser === OK_USER;
      expect({ label, autoLinked: decision.action === 'auto-link' })
        .toEqual({ label, autoLinked: shouldAutoLink });
    }
  });
});

describe('resolveAccountDecision — targeted branches', () => {
  const base: ResolutionInput = {
    provider: 'github',
    providerUserId: 'prov-123',
    email: 'ada@example.com',
    emailVerified: true,
    linkToUserId: null,
    identity: { found: false, user: null },
    emailUser: null,
  };

  test('(a) known identity signs in without requiring email trust', () => {
    const decision = resolveAccountDecision({
      ...base,
      email: null,
      emailVerified: false,
      identity: { found: true, user: OK_USER },
    });
    expect(decision).toEqual({ action: 'sign-in', user: OK_USER });
  });

  test('(b) verified email match auto-links to the existing account', () => {
    expect(resolveAccountDecision({ ...base, emailUser: OK_USER }))
      .toEqual({ action: 'auto-link', user: OK_USER });
  });

  test('(c) verified email with no account routes to signup with the canonical address', () => {
    const decision = resolveAccountDecision({ ...base, email: '  Ada@Example.COM ' });
    expect(decision).toEqual({ action: 'signup', email: 'ada@example.com' });
  });

  test('(d) unverified email is rejected with the stable unverified-email code', () => {
    expect(resolveAccountDecision({ ...base, emailVerified: false, emailUser: OK_USER }))
      .toEqual({ action: 'reject', code: 'unverified-email' });
  });

  test('a verified claim from an untrusted provider is treated as unverified', () => {
    expect(AUTO_LINK_TRUSTED_PROVIDERS.has('bitbucket')).toBe(false);
    expect(resolveAccountDecision({ ...base, provider: 'bitbucket', emailUser: OK_USER }))
      .toEqual({ action: 'reject', code: 'unverified-email' });
  });

  test('a dangling identity (deleted user) is refused as disabled', () => {
    expect(resolveAccountDecision({ ...base, identity: { found: true, user: null } }))
      .toEqual({ action: 'reject', code: 'account-disabled' });
  });

  test('disabled and not-yet-verified accounts are refused on both admission paths', () => {
    expect(resolveAccountDecision({ ...base, identity: { found: true, user: DISABLED_USER } }))
      .toEqual({ action: 'reject', code: 'account-disabled' });
    expect(resolveAccountDecision({ ...base, identity: { found: true, user: UNVERIFIED_USER } }))
      .toEqual({ action: 'reject', code: 'account-not-verified' });
    expect(resolveAccountDecision({ ...base, emailUser: DISABLED_USER }))
      .toEqual({ action: 'reject', code: 'account-disabled' });
    expect(resolveAccountDecision({ ...base, emailUser: UNVERIFIED_USER }))
      .toEqual({ action: 'reject', code: 'account-not-verified' });
  });

  test('a missing provider user id is rejected as an incomplete profile', () => {
    expect(resolveAccountDecision({ ...base, providerUserId: null }))
      .toEqual({ action: 'reject', code: 'OAuthProfileIncomplete' });
  });
});

describe('canonicalizeEmail', () => {
  test('lower-cases and trims, and refuses empty/non-string input', () => {
    expect(canonicalizeEmail('  Ada@Example.COM ')).toBe('ada@example.com');
    expect(canonicalizeEmail('')).toBeNull();
    expect(canonicalizeEmail('   ')).toBeNull();
    expect(canonicalizeEmail(undefined)).toBeNull();
    expect(canonicalizeEmail(42)).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Part 2 — orchestrator against a fake store
// ---------------------------------------------------------------------------

interface FakeStoreConfig {
  identityUserId?: string | null;
  usersById?: Record<string, ResolutionUser>;
  usersByEmail?: Record<string, ResolutionUser>;
  linkResult?: { success: boolean; code?: any };
}

function makeStore(config: FakeStoreConfig = {}) {
  const calls = {
    linkIdentity: [] as any[],
    recordIdentityLogin: [] as any[],
    recordUserLogin: [] as string[],
    createPendingSignup: [] as any[],
  };
  const store: ResolutionStore = {
    async getIdentity() {
      return config.identityUserId !== undefined
        ? { found: true, userId: config.identityUserId }
        : { found: false, userId: null };
    },
    async getUserById(userId) {
      return config.usersById?.[userId] ?? null;
    },
    async getUserByEmail(email) {
      return config.usersByEmail?.[email] ?? null;
    },
    async linkIdentity(userId, identity) {
      calls.linkIdentity.push({ userId, identity });
      return config.linkResult ?? { success: true };
    },
    async recordIdentityLogin(provider, providerUserId, email, emailVerified) {
      calls.recordIdentityLogin.push({ provider, providerUserId, email, emailVerified });
    },
    async recordUserLogin(userId) {
      calls.recordUserLogin.push(userId);
    },
    async createPendingSignup(provider, providerUserId, email, account, profile) {
      calls.createPendingSignup.push({ provider, providerUserId, email, account, profile });
      return { id: 'pending-1' };
    },
  };
  return { store, calls };
}

const makePayload = (overrides: any = {}) => ({
  user: { email: 'Ada@Example.com', name: 'Ada', ...overrides.user },
  account: {
    providerAccountId: 'prov-123',
    access_token: 'tok',
    refresh_token: null,
    expires_at: 1_700_000_000,
    ...overrides.account,
  },
  profile: {
    email: 'Ada@Example.com',
    email_verified: true,
    login: 'ada',
    name: 'Ada L.',
    avatar_url: 'https://example.com/a.png',
    html_url: 'https://github.com/ada',
    ...overrides.profile,
  },
});

describe('resolveOAuthSignIn — orchestration', () => {
  test('(a) known identity: signs in, refreshes identity + user login stamps, adopts user', async () => {
    const { store, calls } = makeStore({ identityUserId: OK_USER.id, usersById: { [OK_USER.id]: OK_USER } });
    const payload = makePayload();

    const result = await resolveOAuthSignIn('github', payload, null, store);

    expect(result).toBe(true);
    expect(payload.user).toMatchObject({ id: OK_USER.id, email: OK_USER.email, name: OK_USER.name });
    expect(calls.recordIdentityLogin).toEqual([
      { provider: 'github', providerUserId: 'prov-123', email: 'ada@example.com', emailVerified: true },
    ]);
    expect(calls.recordUserLogin).toEqual([OK_USER.id]);
    expect(calls.linkIdentity).toHaveLength(0);
  });

  test('(b) verified email match: links the identity, then signs in', async () => {
    const { store, calls } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });
    const payload = makePayload();

    const result = await resolveOAuthSignIn('github', payload, null, store);

    expect(result).toBe(true);
    expect(payload.user).toMatchObject({ id: OK_USER.id });
    expect(calls.linkIdentity).toHaveLength(1);
    expect(calls.linkIdentity[0].userId).toBe(OK_USER.id);
    expect(calls.linkIdentity[0].identity).toMatchObject({
      provider: 'github',
      providerUserId: 'prov-123',
      email: 'ada@example.com',
      emailVerified: true,
      username: 'ada',
    });
  });

  test('(b) a failed auto-link refuses the sign-in with the store code — never an unrecorded login', async () => {
    const { store, calls } = makeStore({
      usersByEmail: { 'ada@example.com': OK_USER },
      linkResult: { success: false, code: 'provider-already-linked' },
    });
    const payload = makePayload();

    const result = await resolveOAuthSignIn('github', payload, null, store);

    expect(result).toBe('/login?error=provider-already-linked');
    expect(payload.user.id).toBeUndefined();
    expect(calls.recordUserLogin).toHaveLength(0);
  });

  test('(c) verified new email: persists a pending signup and redirects to onboarding', async () => {
    const { store, calls } = makeStore();
    const payload = makePayload();

    const result = await resolveOAuthSignIn('github', payload, null, store);

    expect(result).toBe('/signup/oauth?token=pending-1');
    expect(calls.createPendingSignup).toHaveLength(1);
    expect(calls.createPendingSignup[0]).toMatchObject({
      provider: 'github',
      providerUserId: 'prov-123',
      email: 'ada@example.com',
    });
    // The stored profile keeps the provider's verified claim for the signup completion path.
    expect(calls.createPendingSignup[0].profile).toMatchObject({
      email: 'ada@example.com',
      email_verified: true,
    });
  });

  test('(d) unverified email: rejects with unverified-email and persists nothing', async () => {
    const { store, calls } = makeStore({ usersByEmail: { 'ada@example.com': OK_USER } });
    const payload = makePayload({ profile: { email_verified: false } });

    const result = await resolveOAuthSignIn('github', payload, null, store);

    expect(result).toBe('/login?error=unverified-email');
    expect(calls.linkIdentity).toHaveLength(0);
    expect(calls.createPendingSignup).toHaveLength(0);
    expect(calls.recordUserLogin).toHaveLength(0);
  });

  test('signed-in link intent attaches to the session user even with an unverified email', async () => {
    const { store, calls } = makeStore();
    const payload = makePayload({ profile: { email_verified: false } });

    const result = await resolveOAuthSignIn('gitlab', payload, 'session-user', store);

    expect(result).toBe('/ade/dashboard/linked-accounts?linked=true');
    expect(calls.linkIdentity).toHaveLength(1);
    expect(calls.linkIdentity[0].userId).toBe('session-user');
  });

  test('a failed explicit link reports back on the linked-accounts page', async () => {
    const { store } = makeStore({ linkResult: { success: false, code: 'provider-identity-claimed' } });

    const result = await resolveOAuthSignIn('gitlab', makePayload(), 'session-user', store);

    expect(result).toBe(
      '/ade/dashboard/linked-accounts?error=Failed to link account. It may already be linked to another user.'
    );
  });

  test('missing provider email rejects with the email-required code', async () => {
    const { store } = makeStore();
    const payload = makePayload({ user: { email: null }, profile: { email: null } });

    expect(await resolveOAuthSignIn('github', payload, null, store)).toBe(
      '/login?error=OAuthEmailRequired'
    );
  });

  test('missing provider account id rejects with the profile-incomplete code', async () => {
    const { store } = makeStore();
    const payload = makePayload({ account: { providerAccountId: null } });

    expect(await resolveOAuthSignIn('github', payload, null, store)).toBe(
      '/login?error=OAuthProfileIncomplete'
    );
  });
});
