/**
 * `provisionFirstTenant` server action tests (OLO-4.1 #4205, OLO-4.3 #4207).
 *
 * Since OLO-4.3 the action is a thin session wrapper over the shared REST
 * provisioning helper (`first-tenant-provisioning.ts`): it resolves the
 * caller's identity from the server session (never from the client), delegates
 * to the atomic `POST /v1/onboarding/first-tenant` endpoint, and maps the
 * `tenant-cap-reached` conflict onto the wizard's "already belongs to a
 * tenant" guidance.
 */
const mockProvisionViaRest = jest.fn<Promise<unknown>, unknown[]>();

jest.mock('../../lib/auth/first-tenant-provisioning', () => ({
  provisionFirstTenantViaRest: (...args: unknown[]) => mockProvisionViaRest(...args),
}));

// Mocked explicitly: the `^@lib/` moduleNameMapper outranks the shared
// server-session mock mapping, so the action would otherwise pull in next-auth.
jest.mock('@lib/auth/server-session', () => ({
  getAuthSession: jest.fn(async () => null),
}));

import { getAuthSession } from '@lib/auth/server-session';
import { provisionFirstTenant } from '../../lib/auth/first-tenant-actions';

const mockGetAuthSession = getAuthSession as jest.Mock;

beforeEach(() => {
  jest.clearAllMocks();
  mockGetAuthSession.mockResolvedValue({
    user: { user_id: 'user-1', email: 'ada@example.com', name: 'Ada' },
  });
  mockProvisionViaRest.mockResolvedValue({
    success: true,
    tenant: { id: 't-1', name: 'Acme Corp', slug: 'acme' },
  });
});

describe('provisionFirstTenant', () => {
  it('delegates to the shared REST provisioning helper with the session identity', async () => {
    const result = await provisionFirstTenant('Acme Corp', 'acme');

    expect(result).toEqual({
      success: true,
      tenant: { id: 't-1', name: 'Acme Corp', slug: 'acme' },
    });
    expect(mockProvisionViaRest).toHaveBeenCalledWith(
      { user_id: 'user-1', email: 'ada@example.com', name: 'Ada' },
      'Acme Corp',
      'acme'
    );
  });

  it('refuses without an authenticated session', async () => {
    mockGetAuthSession.mockResolvedValue(null);

    const result = await provisionFirstTenant('Acme', 'acme');

    expect(result).toEqual({
      success: false,
      error: expect.stringMatching(/session has expired/i),
    });
    expect(mockProvisionViaRest).not.toHaveBeenCalled();
  });

  it('maps tenant-cap-reached onto the wizard "already belongs" guidance', async () => {
    mockProvisionViaRest.mockResolvedValue({
      success: false,
      error: 'Your account has reached its tenant limit.',
      code: 'tenant-cap-reached',
    });

    const result = await provisionFirstTenant('Another Org', 'another');

    expect(result).toEqual({
      success: false,
      error: expect.stringMatching(/already belongs to a tenant/i),
    });
  });

  it('passes other provisioning failures through unchanged', async () => {
    mockProvisionViaRest.mockResolvedValue({
      success: false,
      error: 'A tenant with this slug already exists',
      code: 'tenant-slug-taken',
    });

    const result = await provisionFirstTenant('Acme', 'acme');

    expect(result).toMatchObject({
      success: false,
      error: 'A tenant with this slug already exists',
    });
  });
});
