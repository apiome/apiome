/**
 * `provisionFirstTenant` server action tests (OLO-4.1, #4205).
 *
 * The action creates the authenticated user's first tenant from the onboarding
 * wizard: tenant + membership + administrator role + free-tier entitlements +
 * sample project, reusing the same helpers as OAuth signup. Covers the misuse
 * safeguards (session-derived user, zero-membership refusal, server-side
 * re-validation), the compensation path (tenant deleted, user never touched),
 * and the best-effort tail (entitlements/sample project never undo a tenant).
 */
const mockCreateTenant = jest.fn<Promise<string>, unknown[]>();
const mockAddUserToTenant = jest.fn<Promise<string>, unknown[]>();
const mockAddTenantAdministrator = jest.fn<Promise<string>, unknown[]>();
const mockDeleteTenant = jest.fn<Promise<string>, unknown[]>();
const mockProvisionSampleProject = jest.fn<Promise<string>, unknown[]>();
const mockInsertFreeTierEntitlements = jest.fn<Promise<void>, unknown[]>();
const mockGetTenantsForUser = jest.fn<Promise<string>, [string]>();

jest.mock('../../lib/db/admin-helper', () => ({
  createTenant: (...args: unknown[]) => mockCreateTenant(...args),
  addUserToTenant: (...args: unknown[]) => mockAddUserToTenant(...args),
  addTenantAdministrator: (...args: unknown[]) => mockAddTenantAdministrator(...args),
  deleteTenant: (...args: unknown[]) => mockDeleteTenant(...args),
  provisionSampleProject: (...args: unknown[]) => mockProvisionSampleProject(...args),
}));

jest.mock('../../lib/db/oauth-signup', () => ({
  insertFreeTierEntitlements: (...args: unknown[]) => mockInsertFreeTierEntitlements(...args),
}));

jest.mock('../../lib/db/helper', () => ({
  getTenantsForUser: (userId: string) => mockGetTenantsForUser(userId),
}));

// Mocked explicitly: the `^@lib/` moduleNameMapper outranks the shared
// server-session mock mapping, so the action would otherwise pull in next-auth.
jest.mock('@lib/auth/server-session', () => ({
  getAuthSession: jest.fn(async () => null),
}));

import { getAuthSession } from '@lib/auth/server-session';
import { provisionFirstTenant } from '../../lib/auth/first-tenant-actions';

const mockGetAuthSession = getAuthSession as jest.Mock;

const ok = (payload: object) => JSON.stringify({ success: true, ...payload });
const fail = (error: string) => JSON.stringify({ success: false, error });

/** Puts every mock into the happy-path state for user `user-1` / tenant `t-1`. */
const primeHappyPath = () => {
  mockGetAuthSession.mockResolvedValue({ user: { user_id: 'user-1' } });
  mockGetTenantsForUser.mockResolvedValue(JSON.stringify([]));
  mockCreateTenant.mockResolvedValue(ok({ tenant: { id: 't-1' } }));
  mockAddUserToTenant.mockResolvedValue(ok({}));
  mockAddTenantAdministrator.mockResolvedValue(ok({}));
  mockDeleteTenant.mockResolvedValue(ok({}));
  mockProvisionSampleProject.mockResolvedValue(ok({ project_id: 'p-1' }));
  mockInsertFreeTierEntitlements.mockResolvedValue(undefined);
};

beforeEach(() => {
  jest.clearAllMocks();
  primeHappyPath();
});

describe('provisionFirstTenant', () => {
  it('provisions tenant, membership, admin role, entitlements, and sample project', async () => {
    const result = await provisionFirstTenant('Acme Corp', 'acme');

    expect(result).toEqual({
      success: true,
      tenant: { id: 't-1', name: 'Acme Corp', slug: 'acme' },
    });
    expect(mockCreateTenant).toHaveBeenCalledWith('Acme Corp', '', 'acme', true);
    expect(mockAddUserToTenant).toHaveBeenCalledWith('t-1', 'user-1');
    expect(mockAddTenantAdministrator).toHaveBeenCalledWith('t-1', 'user-1');
    expect(mockInsertFreeTierEntitlements).toHaveBeenCalledWith('user-1');
    expect(mockProvisionSampleProject).toHaveBeenCalledWith('t-1', 'user-1');
    expect(mockDeleteTenant).not.toHaveBeenCalled();
  });

  it('derives the slug from the organization name when none is entered', async () => {
    const result = await provisionFirstTenant('Acme, Inc.', '  ');

    expect(result).toEqual({
      success: true,
      tenant: { id: 't-1', name: 'Acme, Inc.', slug: 'acme-inc' },
    });
    expect(mockCreateTenant).toHaveBeenCalledWith('Acme, Inc.', '', 'acme-inc', true);
  });

  it('refuses without an authenticated session', async () => {
    mockGetAuthSession.mockResolvedValue(null);

    const result = await provisionFirstTenant('Acme', 'acme');

    expect(result).toEqual({
      success: false,
      error: expect.stringMatching(/session has expired/i),
    });
    expect(mockCreateTenant).not.toHaveBeenCalled();
  });

  it('requires an organization name', async () => {
    const result = await provisionFirstTenant('   ', 'acme');

    expect(result).toEqual({ success: false, error: expect.stringMatching(/name is required/i) });
    expect(mockCreateTenant).not.toHaveBeenCalled();
  });

  it('re-validates the slug server-side', async () => {
    const result = await provisionFirstTenant('Acme', 'not a slug!');

    expect(result).toEqual({
      success: false,
      error: expect.stringMatching(/lowercase letters, numbers, and dashes/i),
    });
    expect(mockCreateTenant).not.toHaveBeenCalled();
  });

  it('refuses when the user already belongs to a tenant', async () => {
    mockGetTenantsForUser.mockResolvedValue(JSON.stringify([{ id: 't-existing', name: 'Acme' }]));

    const result = await provisionFirstTenant('Another Org', 'another');

    expect(result).toEqual({
      success: false,
      error: expect.stringMatching(/already belongs to a tenant/i),
    });
    expect(mockCreateTenant).not.toHaveBeenCalled();
  });

  it('proceeds when the membership pre-check fails (fail open, logged)', async () => {
    const consoleError = jest.spyOn(console, 'error').mockImplementation(() => undefined);
    mockGetTenantsForUser.mockRejectedValue(new Error('db down'));

    const result = await provisionFirstTenant('Acme', 'acme');

    expect(result.success).toBe(true);
    expect(mockCreateTenant).toHaveBeenCalled();
    consoleError.mockRestore();
  });

  it('surfaces a createTenant failure (e.g. slug taken) without compensation', async () => {
    mockCreateTenant.mockResolvedValue(fail('A tenant with this slug already exists'));

    const result = await provisionFirstTenant('Acme', 'acme');

    expect(result).toEqual({ success: false, error: 'A tenant with this slug already exists' });
    expect(mockAddUserToTenant).not.toHaveBeenCalled();
    expect(mockDeleteTenant).not.toHaveBeenCalled();
  });

  it('deletes the tenant when the membership insert fails', async () => {
    mockAddUserToTenant.mockResolvedValue(fail('membership insert failed'));

    const result = await provisionFirstTenant('Acme', 'acme');

    expect(result).toEqual({ success: false, error: 'membership insert failed' });
    expect(mockDeleteTenant).toHaveBeenCalledWith('t-1');
    expect(mockAddTenantAdministrator).not.toHaveBeenCalled();
  });

  it('deletes the tenant when the administrator grant fails', async () => {
    mockAddTenantAdministrator.mockResolvedValue(fail('role insert failed'));

    const result = await provisionFirstTenant('Acme', 'acme');

    expect(result).toEqual({ success: false, error: 'role insert failed' });
    expect(mockDeleteTenant).toHaveBeenCalledWith('t-1');
    expect(mockInsertFreeTierEntitlements).not.toHaveBeenCalled();
  });

  it('still succeeds when the entitlement seed throws (tenant already committed)', async () => {
    const consoleError = jest.spyOn(console, 'error').mockImplementation(() => undefined);
    mockInsertFreeTierEntitlements.mockRejectedValue(new Error('entitlements down'));

    const result = await provisionFirstTenant('Acme', 'acme');

    expect(result.success).toBe(true);
    expect(mockDeleteTenant).not.toHaveBeenCalled();
    consoleError.mockRestore();
  });

  it('still succeeds when the sample project cannot be provisioned', async () => {
    mockProvisionSampleProject.mockResolvedValue(fail('sample project failed'));

    const result = await provisionFirstTenant('Acme', 'acme');

    expect(result.success).toBe(true);
    expect(mockDeleteTenant).not.toHaveBeenCalled();
  });
});
