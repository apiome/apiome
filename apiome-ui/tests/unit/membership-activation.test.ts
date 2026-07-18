/**
 * Invited-user pending-membership activation tests (OLO-4.4, #4208).
 *
 * `activateMembershipViaRest` calls `POST /v1/onboarding/membership-activation`
 * with a session-minted JWT and maps the endpoint's structured codes
 * (`membership-not-found`, `membership-suspended`). The sign-in hook
 * `activatePendingMembershipForLogin` only fires the REST call when the
 * resolved landing tenant's membership is actually `pending`, and never
 * throws — an activation failure must not break the login.
 */
const mockCreateRestAuthHeaders = jest.fn<Record<string, string>, unknown[]>();

jest.mock('../../lib/rest-auth', () => ({
  createRestAuthHeaders: (...args: unknown[]) => mockCreateRestAuthHeaders(...args),
  REST_API_BASE_URL: 'http://rest.test/v1',
}));

const mockGetTenantMembershipsForUser = jest.fn<Promise<string>, [string]>();

jest.mock('../../lib/db/helper', () => ({
  getTenantMembershipsForUser: (userId: string) => mockGetTenantMembershipsForUser(userId),
}));

import {
  activateMembershipViaRest,
  activatePendingMembershipForLogin,
} from '../../lib/auth/membership-activation';

const mockFetch = jest.fn<Promise<unknown>, unknown[]>();
(global as { fetch?: unknown }).fetch = mockFetch;

const USER = { user_id: 'user-1', email: 'ada@example.com', name: 'Ada' };
const TENANT = 't-inviting';

const jsonResponse = (status: number, body: unknown) => ({
  status,
  ok: status >= 200 && status < 300,
  json: async () => body,
});

const tenantRows = (...tenants: Array<{ id: string; name: string; status?: string }>) =>
  JSON.stringify(tenants);

beforeEach(() => {
  jest.clearAllMocks();
  mockCreateRestAuthHeaders.mockReturnValue({
    'Content-Type': 'application/json',
    Authorization: 'Bearer test-token',
  });
  mockFetch.mockResolvedValue(jsonResponse(200, { status: 'activated', tenant_id: TENANT }));
});

describe('activateMembershipViaRest', () => {
  it('activates through the REST endpoint with the caller identity', async () => {
    const result = await activateMembershipViaRest(USER, TENANT);

    expect(result).toEqual({ success: true, status: 'activated' });
    expect(mockCreateRestAuthHeaders).toHaveBeenCalledWith(USER);
    expect(mockFetch).toHaveBeenCalledWith(
      'http://rest.test/v1/onboarding/membership-activation',
      expect.objectContaining({
        method: 'POST',
        cache: 'no-store',
        headers: expect.objectContaining({ Authorization: 'Bearer test-token' }),
      })
    );
    expect(JSON.parse((mockFetch.mock.calls[0][1] as { body: string }).body)).toEqual({
      tenant_id: TENANT,
    });
  });

  it('reports an already-active membership as success', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse(200, { status: 'already-active', tenant_id: TENANT }));

    await expect(activateMembershipViaRest(USER, TENANT)).resolves.toEqual({
      success: true,
      status: 'already-active',
    });
  });

  it('maps the membership-not-found code', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse(404, {
        detail: { code: 'membership-not-found', message: 'You are not a member of this tenant' },
      })
    );

    await expect(activateMembershipViaRest(USER, TENANT)).resolves.toEqual({
      success: false,
      error: 'You are not a member of this tenant',
      code: 'membership-not-found',
    });
  });

  it('maps the membership-suspended code', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse(403, { detail: { code: 'membership-suspended', message: 'Suspended' } })
    );

    const result = await activateMembershipViaRest(USER, TENANT);
    expect(result).toEqual({ success: false, error: 'Suspended', code: 'membership-suspended' });
  });

  it('degrades to a plain error when the service is unreachable', async () => {
    const consoleError = jest.spyOn(console, 'error').mockImplementation(() => undefined);
    mockFetch.mockRejectedValueOnce(new Error('ECONNREFUSED'));

    const result = await activateMembershipViaRest(USER, TENANT);
    expect(result.success).toBe(false);
    consoleError.mockRestore();
  });

  it('degrades to a plain error on an unexpected response body', async () => {
    mockFetch.mockResolvedValueOnce({
      status: 500,
      ok: false,
      json: async () => {
        throw new Error('not json');
      },
    });

    const result = await activateMembershipViaRest(USER, TENANT);
    expect(result).toEqual({ success: false, error: 'Activation failed with status 500' });
  });
});

describe('activatePendingMembershipForLogin', () => {
  it('activates when the landing tenant membership is pending', async () => {
    mockGetTenantMembershipsForUser.mockResolvedValueOnce(
      tenantRows({ id: TENANT, name: 'Acme', status: 'pending' })
    );

    await activatePendingMembershipForLogin(USER, TENANT);

    expect(mockFetch).toHaveBeenCalledTimes(1);
    expect(JSON.parse((mockFetch.mock.calls[0][1] as { body: string }).body)).toEqual({
      tenant_id: TENANT,
    });
  });

  it('makes no REST call for an already-active membership', async () => {
    mockGetTenantMembershipsForUser.mockResolvedValueOnce(
      tenantRows({ id: TENANT, name: 'Acme', status: 'active' })
    );

    await activatePendingMembershipForLogin(USER, TENANT);

    expect(mockFetch).not.toHaveBeenCalled();
  });

  it('makes no REST call when the user has no membership in the landing tenant', async () => {
    mockGetTenantMembershipsForUser.mockResolvedValueOnce(
      tenantRows({ id: 'other-tenant', name: 'Other', status: 'pending' })
    );

    await activatePendingMembershipForLogin(USER, TENANT);

    expect(mockFetch).not.toHaveBeenCalled();
  });

  it('is a no-op for a tenant-less login', async () => {
    await activatePendingMembershipForLogin(USER, null);

    expect(mockGetTenantMembershipsForUser).not.toHaveBeenCalled();
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it('never throws when the activation call fails', async () => {
    const consoleError = jest.spyOn(console, 'error').mockImplementation(() => undefined);
    mockGetTenantMembershipsForUser.mockResolvedValueOnce(
      tenantRows({ id: TENANT, name: 'Acme', status: 'pending' })
    );
    mockFetch.mockRejectedValueOnce(new Error('rest down'));

    await expect(activatePendingMembershipForLogin(USER, TENANT)).resolves.toBeUndefined();
    consoleError.mockRestore();
  });

  it('never throws when the membership lookup fails', async () => {
    const consoleError = jest.spyOn(console, 'error').mockImplementation(() => undefined);
    mockGetTenantMembershipsForUser.mockRejectedValueOnce(new Error('db down'));

    await expect(activatePendingMembershipForLogin(USER, TENANT)).resolves.toBeUndefined();
    expect(mockFetch).not.toHaveBeenCalled();
    consoleError.mockRestore();
  });
});
