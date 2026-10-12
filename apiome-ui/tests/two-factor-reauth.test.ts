/**
 * @jest-environment node
 *
 * Fresh re-authentication for two-factor changes on accounts without a password (TFA-1.1, #5655).
 *
 * `allowPasswordless` lets an account with no password manage its second factor; this gate is what
 * stops any old session of such an account from doing so. Pinned here: which requests it looks at,
 * that an account with a password is left to the plugin, and that only a recent sign-in passes.
 */

import { beforeEach, describe, expect, jest, test } from '@jest/globals';

jest.mock('better-auth/api', () => ({
  getAuthoritativeSessionFromCtx: jest.fn(),
  APIError: class APIError extends Error {
    status: string;
    body: { message?: string; code?: string };
    constructor(status: string, body: { message?: string; code?: string } = {}) {
      super(body.message);
      this.status = status;
      this.body = body;
    }
  },
}));

import {
  REAUTH_GATED_PATHS,
  REAUTH_REQUIRED_MESSAGE,
  hasCredentialPassword,
  twoFactorReauthHandler,
  type ReauthSession,
} from '@lib/auth/two-factor-reauth';
import {
  REAUTH_REQUIRED_CODE,
  REAUTH_WINDOW_MINUTES,
  REAUTH_WINDOW_MS,
  isSessionFresh,
} from '@lib/auth/two-factor-policy';

const NOW = Date.parse('2026-10-11T12:00:00Z');
const USER_ID = 'user-1';
const MINUTE = 60_000;

const OAUTH_ONLY = [{ providerId: 'github' }];
const WITH_PASSWORD = [{ providerId: 'github' }, { providerId: 'credential', password: '$2b$10$hash' }];

/** Run the gate for a request on `path` by an account with `accounts`, signed in `ageMs` ago. */
async function gate(
  path: string | undefined,
  accounts: { providerId: string; password?: string | null }[] | null,
  ageMs: number | null
) {
  const findAccounts = jest.fn(async () => accounts);
  const session: ReauthSession | null =
    ageMs === null ? null : { user: { id: USER_ID }, session: { createdAt: new Date(NOW - ageMs) } };
  const readSession = jest.fn(async () => session);
  const outcome = await twoFactorReauthHandler(
    { path, context: { internalAdapter: { findAccounts } } },
    readSession,
    NOW
  ).then(
    () => 'allowed' as const,
    (error: { status?: string; body?: { code?: string; message?: string } }) => error
  );
  return { outcome, findAccounts, readSession };
}

beforeEach(() => {
  jest.clearAllMocks();
});

describe('isSessionFresh', () => {
  test('the window is ten minutes', () => {
    expect(REAUTH_WINDOW_MINUTES).toBe(10);
    expect(REAUTH_WINDOW_MS).toBe(600_000);
  });

  test.each([
    ['just created', 0, true],
    ['nine minutes old', 9 * MINUTE, true],
    ['one millisecond inside the window', 10 * MINUTE - 1, true],
    ['exactly ten minutes old', 10 * MINUTE, false],
    ['a day old', 24 * 60 * MINUTE, false],
    ['dated in the future', -MINUTE, false],
  ])('%s → %p', (_name, ageMs, expected) => {
    expect(isSessionFresh(new Date(NOW - ageMs), NOW)).toBe(expected);
  });

  test('accepts a date, an ISO string or a timestamp', () => {
    const created = NOW - MINUTE;
    expect(isSessionFresh(new Date(created), NOW)).toBe(true);
    expect(isSessionFresh(new Date(created).toISOString(), NOW)).toBe(true);
    expect(isSessionFresh(created, NOW)).toBe(true);
  });

  test.each([null, undefined, 'not a date', Number.NaN])('refuses %p', (value) => {
    expect(isSessionFresh(value as never, NOW)).toBe(false);
  });
});

describe('hasCredentialPassword', () => {
  test.each([
    ['a credential account with a password', WITH_PASSWORD, true],
    ['provider accounts only', OAUTH_ONLY, false],
    ['a credential account with no password', [{ providerId: 'credential', password: null }], false],
    ['a credential account with an empty password', [{ providerId: 'credential', password: '' }], false],
    ['no accounts', [], false],
    ['an unreadable account list', null, false],
  ])('%s → %p', (_name, accounts, expected) => {
    expect(hasCredentialPassword(accounts)).toBe(expected);
  });
});

describe('twoFactorReauthHandler', () => {
  test('guards exactly the three endpoints that change the second factor', () => {
    expect([...REAUTH_GATED_PATHS].sort()).toEqual([
      '/two-factor/disable',
      '/two-factor/enable',
      '/two-factor/generate-backup-codes',
    ]);
  });

  test.each([
    '/two-factor/verify-totp',
    '/two-factor/verify-backup-code',
    '/sign-in/email',
    '/oauth2/callback/github',
    undefined,
  ])('does not look at %p', async (path) => {
    const { outcome, readSession } = await gate(path, OAUTH_ONLY, 24 * 60 * MINUTE);
    expect(outcome).toBe('allowed');
    expect(readSession).not.toHaveBeenCalled();
  });

  describe.each([...REAUTH_GATED_PATHS])('%s', (path) => {
    test('leaves an account with a password to the plugin, however old the session', async () => {
      expect((await gate(path, WITH_PASSWORD, 30 * 24 * 60 * MINUTE)).outcome).toBe('allowed');
    });

    test('allows a passwordless account that has just signed in', async () => {
      expect((await gate(path, OAUTH_ONLY, MINUTE)).outcome).toBe('allowed');
    });

    test('refuses a passwordless account whose session is stale', async () => {
      const { outcome } = await gate(path, OAUTH_ONLY, 11 * MINUTE);
      expect(outcome).toMatchObject({
        status: 'FORBIDDEN',
        body: { code: REAUTH_REQUIRED_CODE, message: REAUTH_REQUIRED_MESSAGE },
      });
    });

    test('leaves a request with no session to the endpoint', async () => {
      const { outcome, findAccounts } = await gate(path, OAUTH_ONLY, null);
      expect(outcome).toBe('allowed');
      expect(findAccounts).not.toHaveBeenCalled();
    });
  });

  test('refuses when the account list cannot be read and the session is stale', async () => {
    // No accounts ⇒ no password to fall back on ⇒ freshness is the only proof.
    expect((await gate('/two-factor/disable', null, 11 * MINUTE)).outcome).toMatchObject({
      body: { code: REAUTH_REQUIRED_CODE },
    });
  });

  test('the refusal says what to do and for how long it lasts', () => {
    expect(REAUTH_REQUIRED_MESSAGE).toBe(
      'Sign in again to confirm it is you. Two-factor settings can be changed for 10 minutes after you sign in.'
    );
  });
});
