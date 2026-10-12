/**
 * @jest-environment node
 *
 * `getTwoFactorReauthStatus` — what the Profile page is told about how an account confirms it is
 * them before a two-factor change (TFA-1.1, #5655).
 *
 * The action mirrors the server's gate (`twoFactorReauthHandler`): the same accounts, the same
 * session timestamp. It is advisory, so every failure reports "has a password" — the dialogs then
 * keep asking for one and the server gives the real answer.
 */

const mockGetSession = jest.fn();
const mockFindAccounts = jest.fn();
const mockResolveProviderEnv = jest.fn(async () => ({}));
const mockProviderSummaries = jest.fn();

jest.mock('next/headers', () => ({
  cookies: jest.fn(async () => ({ get: jest.fn(), set: jest.fn() })),
  headers: jest.fn(async () => new Headers()),
}));
jest.mock('@lib/auth/auth', () => ({
  auth: {
    api: { getSession: (...args: unknown[]) => mockGetSession(...args) },
    $context: Promise.resolve({
      internalAdapter: { findAccounts: (...args: unknown[]) => mockFindAccounts(...args) },
    }),
  },
}));
jest.mock('better-auth/api', () => ({
  getAuthoritativeSessionFromCtx: jest.fn(),
  APIError: class extends Error {},
}));
jest.mock('@lib/auth/better-auth-session', () => ({ resolveBetterAuthSecret: () => 'test-secret' }));
jest.mock('@lib/auth/cookie-options', () => ({ getSharedCookieDomain: () => undefined }));
jest.mock('@lib/auth/provider-config-resolver', () => ({
  resolveProviderEnv: (...args: unknown[]) => mockResolveProviderEnv(...args),
}));
jest.mock('@lib/auth/provider-registry', () => ({
  providerSummaries: (...args: unknown[]) => mockProviderSummaries(...args),
}));

import { getTwoFactorReauthStatus } from '@lib/auth/two-factor-profile-actions';

const MINUTE = 60_000;
const ASKS_FOR_PASSWORD = { hasPassword: true, fresh: false, providers: [] };

/** A session for `u1` created `ageMs` ago. */
const sessionAged = (ageMs: number) => ({
  user: { id: 'u1' },
  session: { createdAt: new Date(Date.now() - ageMs) },
});

beforeEach(() => {
  jest.clearAllMocks();
  jest.spyOn(console, 'warn').mockImplementation(() => undefined);
  mockProviderSummaries.mockReturnValue([
    { id: 'github', label: 'GitHub', enabled: true },
    { id: 'gitlab', label: 'GitLab', enabled: true },
    { id: 'google', label: 'Google', enabled: false },
  ]);
});

afterEach(() => {
  jest.restoreAllMocks();
});

describe('getTwoFactorReauthStatus', () => {
  it('reports a passwordless account that has just signed in as fresh', async () => {
    mockGetSession.mockResolvedValue(sessionAged(MINUTE));
    mockFindAccounts.mockResolvedValue([{ providerId: 'github' }]);

    expect(await getTwoFactorReauthStatus()).toEqual({
      hasPassword: false,
      fresh: true,
      providers: [{ id: 'github', label: 'GitHub' }],
    });
    expect(mockFindAccounts).toHaveBeenCalledWith('u1');
  });

  it('reports a passwordless account with an old session as needing to sign in again', async () => {
    mockGetSession.mockResolvedValue(sessionAged(11 * MINUTE));
    mockFindAccounts.mockResolvedValue([{ providerId: 'github' }]);

    expect(await getTwoFactorReauthStatus()).toMatchObject({ hasPassword: false, fresh: false });
  });

  it('offers only providers that are both linked and enabled', async () => {
    mockGetSession.mockResolvedValue(sessionAged(11 * MINUTE));
    // gitlab is enabled but not linked; google is linked but switched off on this installation.
    mockFindAccounts.mockResolvedValue([{ providerId: 'github' }, { providerId: 'google' }]);

    expect((await getTwoFactorReauthStatus()).providers).toEqual([{ id: 'github', label: 'GitHub' }]);
  });

  it('reports an account with a password as such, and looks no further', async () => {
    mockGetSession.mockResolvedValue(sessionAged(MINUTE));
    mockFindAccounts.mockResolvedValue([
      { providerId: 'github' },
      { providerId: 'credential', password: '$2b$10$hash' },
    ]);

    expect(await getTwoFactorReauthStatus()).toEqual(ASKS_FOR_PASSWORD);
    expect(mockProviderSummaries).not.toHaveBeenCalled();
  });

  it.each([
    ['there is no session', () => mockGetSession.mockResolvedValue(null)],
    ['the session cannot be read', () => mockGetSession.mockRejectedValue(new Error('db down'))],
    [
      'the accounts cannot be read',
      () => {
        mockGetSession.mockResolvedValue(sessionAged(MINUTE));
        mockFindAccounts.mockRejectedValue(new Error('db down'));
      },
    ],
  ])('falls back to asking for a password when %s', async (_name, arrange) => {
    arrange();
    expect(await getTwoFactorReauthStatus()).toEqual(ASKS_FOR_PASSWORD);
  });
});
