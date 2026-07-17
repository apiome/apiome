/**
 * Post-login routing rules (OLO-3.3, #4201).
 *
 * Pins the routing contract: zero tenant memberships → onboarding prompt at the
 * default landing (callbackUrl ignored so deep links cannot route around the
 * wizard); members → last-active/default tenant with the callbackUrl honored
 * only when it passes the allowlist. Also covers the db-backed variants used by
 * the NextAuth JWT callback and the login page, including their fail-open
 * behavior on membership-store errors.
 */

const mockGetTenantsForUser = jest.fn<Promise<string>, [string]>();

jest.mock('../../lib/db/helper', () => ({
  getTenantsForUser: (userId: string) => mockGetTenantsForUser(userId),
}));

import { DEFAULT_LOGIN_LANDING } from '@lib/auth/cookie-options';
import {
  decidePostLoginRoute,
  getMembershipTenantIdsForUser,
  pickActiveTenantId,
  resolveActiveTenantForLogin,
  resolvePostLoginRouteForUser,
} from '@lib/auth/post-login-routing';

const tenantRows = (...tenants: Array<{ id: string; name: string }>) => JSON.stringify(tenants);

beforeEach(() => {
  mockGetTenantsForUser.mockReset();
});

describe('pickActiveTenantId', () => {
  it('keeps the last-active tenant when it is still a membership', () => {
    expect(pickActiveTenantId(['t1', 't2'], 't2')).toBe('t2');
  });

  it('falls back to the default (first) tenant when the last-active membership is gone', () => {
    expect(pickActiveTenantId(['t1', 't2'], 'revoked')).toBe('t1');
  });

  it('falls back to the default tenant when there is no last-active tenant', () => {
    expect(pickActiveTenantId(['t1', 't2'], null)).toBe('t1');
    expect(pickActiveTenantId(['t1', 't2'], undefined)).toBe('t1');
  });

  it('returns null for a user with no memberships', () => {
    expect(pickActiveTenantId([], 'anything')).toBeNull();
  });
});

describe('decidePostLoginRoute', () => {
  it('routes zero-tenant users to the onboarding prompt at the default landing', () => {
    expect(decidePostLoginRoute({ membershipTenantIds: [] })).toEqual({
      kind: 'onboarding',
      destination: DEFAULT_LOGIN_LANDING,
      activeTenantId: null,
    });
  });

  it('ignores callbackUrl for zero-tenant users so deep links cannot skip the wizard', () => {
    const route = decidePostLoginRoute({
      membershipTenantIds: [],
      callbackUrl: '/ade/dashboard/projects',
    });
    expect(route.kind).toBe('onboarding');
    expect(route.destination).toBe(DEFAULT_LOGIN_LANDING);
  });

  it('routes members to an allowlisted relative callbackUrl with their last-active tenant', () => {
    const route = decidePostLoginRoute({
      membershipTenantIds: ['t1', 't2'],
      lastActiveTenantId: 't2',
      callbackUrl: '/ade/dashboard/projects',
    });
    expect(route).toEqual({
      kind: 'dashboard',
      destination: '/ade/dashboard/projects',
      activeTenantId: 't2',
    });
  });

  it('falls back to the default landing when the callbackUrl is not allowlisted', () => {
    const route = decidePostLoginRoute({
      membershipTenantIds: ['t1'],
      callbackUrl: 'https://evil.example/phish',
    });
    expect(route).toEqual({
      kind: 'dashboard',
      destination: DEFAULT_LOGIN_LANDING,
      activeTenantId: 't1',
    });
  });

  it('rejects protocol-relative callbackUrls (open-redirect vector)', () => {
    const route = decidePostLoginRoute({
      membershipTenantIds: ['t1'],
      callbackUrl: '//evil.example/phish',
    });
    expect(route.destination).toBe(DEFAULT_LOGIN_LANDING);
  });

  it('defaults the destination when no callbackUrl was requested', () => {
    const route = decidePostLoginRoute({ membershipTenantIds: ['t1'] });
    expect(route.destination).toBe(DEFAULT_LOGIN_LANDING);
  });
});

describe('getMembershipTenantIdsForUser', () => {
  it('returns tenant ids sorted by tenant name (default tenant first)', async () => {
    mockGetTenantsForUser.mockResolvedValueOnce(
      tenantRows({ id: 'tz', name: 'Zeta' }, { id: 'ta', name: 'Acme' })
    );

    await expect(getMembershipTenantIdsForUser('user-1')).resolves.toEqual(['ta', 'tz']);
    expect(mockGetTenantsForUser).toHaveBeenCalledWith('user-1');
  });

  it('returns an empty list for a tenant-less user', async () => {
    mockGetTenantsForUser.mockResolvedValueOnce(tenantRows());
    await expect(getMembershipTenantIdsForUser('user-1')).resolves.toEqual([]);
  });
});

describe('resolveActiveTenantForLogin', () => {
  it('keeps a candidate tenant that is a real membership', async () => {
    mockGetTenantsForUser.mockResolvedValueOnce(
      tenantRows({ id: 't1', name: 'Acme' }, { id: 't2', name: 'Beta' })
    );
    await expect(resolveActiveTenantForLogin('user-1', 't2')).resolves.toBe('t2');
  });

  it('replaces a candidate that is not a membership with the default tenant', async () => {
    mockGetTenantsForUser.mockResolvedValueOnce(tenantRows({ id: 't1', name: 'Acme' }));
    await expect(resolveActiveTenantForLogin('user-1', 'revoked')).resolves.toBe('t1');
  });

  it('resolves null for a tenant-less user', async () => {
    mockGetTenantsForUser.mockResolvedValueOnce(tenantRows());
    await expect(resolveActiveTenantForLogin('user-1', 'stale')).resolves.toBeNull();
  });

  it('fails open to the candidate when the membership lookup throws', async () => {
    const consoleError = jest.spyOn(console, 'error').mockImplementation(() => undefined);
    mockGetTenantsForUser.mockRejectedValueOnce(new Error('db down'));
    await expect(resolveActiveTenantForLogin('user-1', 't9')).resolves.toBe('t9');
    consoleError.mockRestore();
  });
});

describe('resolvePostLoginRouteForUser', () => {
  it('prompts onboarding for a user with zero memberships', async () => {
    mockGetTenantsForUser.mockResolvedValueOnce(tenantRows());
    await expect(
      resolvePostLoginRouteForUser('user-1', { callbackUrl: '/ade/dashboard/projects' })
    ).resolves.toEqual({
      kind: 'onboarding',
      destination: DEFAULT_LOGIN_LANDING,
      activeTenantId: null,
    });
  });

  it('routes a member to their last-active tenant and requested callbackUrl', async () => {
    mockGetTenantsForUser.mockResolvedValueOnce(
      tenantRows({ id: 't1', name: 'Acme' }, { id: 't2', name: 'Beta' })
    );
    await expect(
      resolvePostLoginRouteForUser('user-1', {
        lastActiveTenantId: 't2',
        callbackUrl: '/ade/dashboard/versions',
      })
    ).resolves.toEqual({
      kind: 'dashboard',
      destination: '/ade/dashboard/versions',
      activeTenantId: 't2',
    });
  });

  it('fails open to a dashboard route when the membership lookup throws', async () => {
    const consoleError = jest.spyOn(console, 'error').mockImplementation(() => undefined);
    mockGetTenantsForUser.mockRejectedValueOnce(new Error('db down'));
    await expect(
      resolvePostLoginRouteForUser('user-1', { lastActiveTenantId: 't1' })
    ).resolves.toEqual({
      kind: 'dashboard',
      destination: DEFAULT_LOGIN_LANDING,
      activeTenantId: 't1',
    });
    consoleError.mockRestore();
  });
});
