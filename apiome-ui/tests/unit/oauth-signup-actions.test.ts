/**
 * `completeOAuthSignup` provisioning-path tests (OLO-4.3, #4207).
 *
 * The action creates the user and links the OAuth provider, then flows tenant
 * creation through the shared atomic REST helper — the same single
 * provisioning path as the onboarding wizard. Covers the compensation
 * contract: the REST side is all-or-nothing, so the only cleanup on
 * provisioning failure is deleting the just-created user.
 */
const mockCreateUser = jest.fn<Promise<string>, unknown[]>();
const mockDeleteUser = jest.fn<Promise<string>, unknown[]>();
const mockClearUserPassword = jest.fn<Promise<string>, unknown[]>();
const mockLinkExternalAccount = jest.fn<Promise<string>, unknown[]>();
const mockGetPending = jest.fn<Promise<unknown>, [string]>();
const mockDeletePending = jest.fn<Promise<void>, [string]>();
const mockInsertOneTimeCode = jest.fn<Promise<string>, unknown[]>();
const mockProvisionViaRest = jest.fn<Promise<unknown>, unknown[]>();

jest.mock('../../lib/db/admin-helper', () => ({
  createUser: (...args: unknown[]) => mockCreateUser(...args),
  deleteUser: (...args: unknown[]) => mockDeleteUser(...args),
  clearUserPassword: (...args: unknown[]) => mockClearUserPassword(...args),
}));

jest.mock('../../lib/db/helper', () => ({
  linkExternalAccount: (...args: unknown[]) => mockLinkExternalAccount(...args),
}));

jest.mock('../../lib/db/oauth-signup', () => ({
  getOauthSignupPendingById: (id: string) => mockGetPending(id),
  deleteOauthSignupPendingById: (id: string) => mockDeletePending(id),
  insertAuthOneTimeCode: (...args: unknown[]) => mockInsertOneTimeCode(...args),
}));

jest.mock('../../lib/auth/first-tenant-provisioning', () => ({
  provisionFirstTenantViaRest: (...args: unknown[]) => mockProvisionViaRest(...args),
}));

import { completeOAuthSignup } from '../../lib/auth/oauth-signup-actions';

const ok = (payload: object) => JSON.stringify({ success: true, ...payload });
const fail = (error: string) => JSON.stringify({ success: false, error });

const PENDING = {
  email: 'Ada@Example.com',
  provider: 'github',
  provider_account_id: 'gh-123',
  account_json: {},
  profile_json: { email_verified: true },
};

/** Puts every mock into the happy-path state for user `user-1` / tenant `t-1`. */
const primeHappyPath = () => {
  mockGetPending.mockResolvedValue({ ...PENDING });
  mockCreateUser.mockResolvedValue(ok({ user: { id: 'user-1' } }));
  mockClearUserPassword.mockResolvedValue(ok({ id: 'user-1' }));
  mockLinkExternalAccount.mockResolvedValue(ok({}));
  mockProvisionViaRest.mockResolvedValue({
    success: true,
    tenant: { id: 't-1', name: 'Acme Corp', slug: 'acme' },
  });
  mockDeleteUser.mockResolvedValue(ok({}));
  mockDeletePending.mockResolvedValue(undefined);
  mockInsertOneTimeCode.mockResolvedValue('code-1');
};

beforeEach(() => {
  jest.clearAllMocks();
  primeHappyPath();
});

describe('completeOAuthSignup', () => {
  it('creates the user then provisions the tenant via the shared REST helper', async () => {
    const result = await completeOAuthSignup('pending-1', 'Ada', 'Acme Corp', 'acme');

    expect(result).toEqual({ success: true, oneTimeCode: 'code-1' });
    expect(mockProvisionViaRest).toHaveBeenCalledWith(
      { user_id: 'user-1', email: 'ada@example.com', name: 'Ada' },
      'Acme Corp',
      'acme'
    );
    expect(mockInsertOneTimeCode).toHaveBeenCalledWith('user-1', 't-1');
    expect(mockDeletePending).toHaveBeenCalledWith('pending-1');
    expect(mockDeleteUser).not.toHaveBeenCalled();
    // OAuth accounts are provisioned password-less so their identity is the sole sign-in method
    // the OLO-2.4 unlink guard protects.
    expect(mockClearUserPassword).toHaveBeenCalledWith('user-1');
  });

  it('deletes the just-created user when tenant provisioning fails', async () => {
    mockProvisionViaRest.mockResolvedValue({
      success: false,
      error: 'A tenant with this slug already exists',
      code: 'tenant-slug-taken',
    });

    const result = await completeOAuthSignup('pending-1', 'Ada', 'Acme Corp', 'acme');

    expect(result).toEqual({ success: false, error: 'A tenant with this slug already exists' });
    expect(mockDeleteUser).toHaveBeenCalledWith('user-1');
    expect(mockInsertOneTimeCode).not.toHaveBeenCalled();
    expect(mockDeletePending).not.toHaveBeenCalled();
  });

  it('deletes the user when provider linking fails, before any provisioning', async () => {
    mockLinkExternalAccount.mockResolvedValue(fail('link failed'));

    const result = await completeOAuthSignup('pending-1', 'Ada', 'Acme Corp', 'acme');

    expect(result).toEqual({ success: false, error: 'link failed' });
    expect(mockDeleteUser).toHaveBeenCalledWith('user-1');
    expect(mockProvisionViaRest).not.toHaveBeenCalled();
  });

  it('validates name and slug before creating anything', async () => {
    const noName = await completeOAuthSignup('pending-1', '  ', 'Acme Corp', 'acme');
    expect(noName).toEqual({ success: false, error: expect.stringMatching(/name is required/i) });

    const badSlug = await completeOAuthSignup('pending-1', 'Ada', 'Acme Corp', 'not a slug!');
    expect(badSlug).toEqual({
      success: false,
      error: expect.stringMatching(/lowercase letters, numbers, and dashes/i),
    });

    expect(mockCreateUser).not.toHaveBeenCalled();
    expect(mockProvisionViaRest).not.toHaveBeenCalled();
  });

  it('refuses when the pending signup session is gone', async () => {
    mockGetPending.mockResolvedValue(null);

    const result = await completeOAuthSignup('pending-1', 'Ada', 'Acme Corp', 'acme');

    expect(result).toEqual({
      success: false,
      error: expect.stringMatching(/expired or invalid/i),
    });
    expect(mockCreateUser).not.toHaveBeenCalled();
  });
});
