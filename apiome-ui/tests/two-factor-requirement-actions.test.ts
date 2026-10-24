/**
 * `getMyTwoFactorRequirement` — the grace notice's read (TFA-1.3, #5657). Session-bound, and fails
 * open: the blocking screen is the server guard's job.
 */

const mockGetAuthSession = jest.fn();
jest.mock('@lib/auth/server-session', () => ({ getAuthSession: () => mockGetAuthSession() }));
jest.mock('../lib/auth/server-session', () => ({ getAuthSession: () => mockGetAuthSession() }));

const mockRead = jest.fn();
jest.mock('../lib/auth/two-factor-requirement', () => ({
  readTwoFactorRequirement: (...args: unknown[]) => mockRead(...args),
}));

import { getMyTwoFactorRequirement } from '../lib/auth/two-factor-requirement-actions';
import { NO_TWO_FACTOR_REQUIREMENT } from '../lib/two-factor-policy';

beforeEach(() => jest.clearAllMocks());

describe('getMyTwoFactorRequirement', () => {
  it('answers for the session user only', async () => {
    const owed = { tenants: [{ tenantName: 'Acme', dueAt: '2026-10-30T12:00:00Z' }], dueAt: '2026-10-30T12:00:00Z', overdue: false };
    mockGetAuthSession.mockResolvedValue({ user: { user_id: 'u-1' } });
    mockRead.mockResolvedValue(owed);
    expect(await getMyTwoFactorRequirement()).toEqual(owed);
    expect(mockRead).toHaveBeenCalledWith('u-1');
  });

  it('owes nothing when signed out', async () => {
    mockGetAuthSession.mockResolvedValue(null);
    expect(await getMyTwoFactorRequirement()).toBe(NO_TWO_FACTOR_REQUIREMENT);
    expect(mockRead).not.toHaveBeenCalled();
  });

  it('fails open on a database error', async () => {
    const warn = jest.spyOn(console, 'warn').mockImplementation(() => undefined);
    mockGetAuthSession.mockResolvedValue({ user: { user_id: 'u-1' } });
    mockRead.mockRejectedValue(new Error('db down'));
    expect(await getMyTwoFactorRequirement()).toBe(NO_TWO_FACTOR_REQUIREMENT);
    warn.mockRestore();
  });
});
