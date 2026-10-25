/**
 * A disabled or deleted account gets no session, by any sign-in method (`account-state-guard.ts`).
 */

jest.mock('better-auth/api', () => ({
  APIError: class APIError extends Error {
    status: string;
    body: { code?: string };
    constructor(status: string, body: { code?: string; message?: string }) {
      super(body?.message);
      this.status = status;
      this.body = body;
    }
  },
}));
jest.mock('../lib/db/db', () => ({ query: jest.fn() }));
const mockSetOverride = jest.fn();
jest.mock('../lib/auth/better-auth-oauth-providers', () => ({
  setOauthRedirectOverride: (path: string) => mockSetOverride(path),
}));
jest.mock('../lib/auth/account-resolution', () => ({
  AUTH_ERROR_CODES: { ACCOUNT_DISABLED: 'account-disabled' },
  loginErrorRedirect: (code: string) => `/login?error=${code}`,
}));

import { accountStateSessionCreateBefore } from '../lib/auth/account-state-guard';

const deps = (state: { enabled: boolean; deleted: boolean } | null) => ({
  readAccountState: jest.fn().mockResolvedValue(state),
});

beforeEach(() => mockSetOverride.mockReset());

describe('accountStateSessionCreateBefore', () => {
  it('admits an enabled, live account', async () => {
    await expect(
      accountStateSessionCreateBefore({ userId: 'u-1' }, deps({ enabled: true, deleted: false }))
    ).resolves.toBeUndefined();
    expect(mockSetOverride).not.toHaveBeenCalled();
  });

  it.each([
    ['disabled', { enabled: false, deleted: false }],
    ['deleted', { enabled: false, deleted: true }],
    ['missing', null],
  ])('refuses a %s account', async (_label, state) => {
    await expect(accountStateSessionCreateBefore({ userId: 'u-1' }, deps(state))).rejects.toMatchObject({
      status: 'FORBIDDEN',
      body: { code: 'account-disabled' },
    });
    // A provider callback lands on the login page's account-disabled message.
    expect(mockSetOverride).toHaveBeenCalledWith('/login?error=account-disabled');
  });

  it('leaves a session with no user id to Better Auth', async () => {
    const d = deps(null);
    await expect(accountStateSessionCreateBefore({}, d)).resolves.toBeUndefined();
    expect(d.readAccountState).not.toHaveBeenCalled();
  });
});
