/**
 * Session-shape mapping tests (OLO-10.12, #5007) for `lib/auth/better-auth-session-shape.ts`.
 *
 * These cover the single source that maps a Better Auth session onto the app contract
 * (`user_id`/`current_tenant_id`) and, critically, that the read-time tenant derivation stays
 * **validated** (against live memberships) and **fail-safe** (any error → no tenant, never a throw),
 * mirroring the NextAuth `jwt` callback it replaces. The membership store and cookie reader are mocked
 * so this is a pure unit test.
 */

const mockResolveActiveTenant = jest.fn();
const mockReadLastActive = jest.fn();

jest.mock('@lib/auth/post-login-routing', () => ({
  resolveActiveTenantForLogin: mockResolveActiveTenant,
}));
jest.mock('@lib/auth/last-active-tenant', () => ({
  readLastActiveTenantId: mockReadLastActive,
}));

import {
  deriveCurrentTenantId,
  toAppSessionUser,
  augmentBetterAuthUser,
} from '@lib/auth/better-auth-session-shape';

beforeEach(() => {
  jest.clearAllMocks();
});

describe('deriveCurrentTenantId', () => {
  it('re-validates the last-active cookie candidate against memberships', async () => {
    mockReadLastActive.mockResolvedValue('cand-tenant');
    mockResolveActiveTenant.mockResolvedValue('validated-tenant');

    const result = await deriveCurrentTenantId('user-1');

    expect(mockResolveActiveTenant).toHaveBeenCalledWith('user-1', 'cand-tenant');
    expect(result).toBe('validated-tenant');
  });

  it('returns undefined when no tenant resolves (tenant-less user)', async () => {
    mockReadLastActive.mockResolvedValue(null);
    mockResolveActiveTenant.mockResolvedValue(null);

    expect(await deriveCurrentTenantId('user-1')).toBeUndefined();
  });

  it('fails safe to undefined when the cookie read throws', async () => {
    mockReadLastActive.mockRejectedValue(new Error('cookie boom'));

    expect(await deriveCurrentTenantId('user-1')).toBeUndefined();
  });

  it('fails safe to undefined when membership validation throws', async () => {
    mockReadLastActive.mockResolvedValue('cand-tenant');
    mockResolveActiveTenant.mockRejectedValue(new Error('db boom'));

    expect(await deriveCurrentTenantId('user-1')).toBeUndefined();
  });
});

describe('toAppSessionUser', () => {
  it('maps id -> user_id and includes the validated tenant', async () => {
    mockReadLastActive.mockResolvedValue('t');
    mockResolveActiveTenant.mockResolvedValue('t1');

    const user = await toAppSessionUser({
      id: 'u1',
      email: 'a@b.co',
      name: 'Ada',
      image: 'http://img',
    });

    expect(user).toEqual({
      user_id: 'u1',
      email: 'a@b.co',
      name: 'Ada',
      image: 'http://img',
      current_tenant_id: 't1',
    });
  });

  it('omits current_tenant_id entirely when none resolves', async () => {
    mockReadLastActive.mockResolvedValue(null);
    mockResolveActiveTenant.mockResolvedValue(null);

    const user = await toAppSessionUser({ id: 'u1', email: 'a@b.co', name: null });

    expect(user).not.toHaveProperty('current_tenant_id');
    expect(user).toEqual({ user_id: 'u1', email: 'a@b.co', name: null, image: null });
  });
});

describe('augmentBetterAuthUser', () => {
  it('preserves native fields and adds user_id + current_tenant_id', async () => {
    mockReadLastActive.mockResolvedValue('t');
    mockResolveActiveTenant.mockResolvedValue('t9');

    const augmented = await augmentBetterAuthUser({
      id: 'u1',
      email: 'a@b.co',
      name: 'Ada',
      emailVerified: true,
    } as { id: string; email: string; name: string; emailVerified: boolean });

    // Native fields kept (so the browser client keeps them and the server reader can still read `id`).
    expect(augmented.id).toBe('u1');
    expect(augmented.emailVerified).toBe(true);
    expect(augmented.user_id).toBe('u1');
    expect(augmented.current_tenant_id).toBe('t9');
  });

  it('omits current_tenant_id when none resolves', async () => {
    mockReadLastActive.mockResolvedValue(null);
    mockResolveActiveTenant.mockResolvedValue(null);

    const augmented = await augmentBetterAuthUser({ id: 'u1', email: 'a@b.co' });

    expect(augmented.user_id).toBe('u1');
    expect(augmented).not.toHaveProperty('current_tenant_id');
  });
});
