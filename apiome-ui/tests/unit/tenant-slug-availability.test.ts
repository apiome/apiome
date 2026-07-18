/**
 * `checkTenantSlugAvailability` server action tests (OLO-4.2, #4206).
 *
 * The action probes `HEAD /v1/tenants/{slug}` with the caller's session
 * identity and maps 404 → available, 200/403 → taken. It never throws:
 * invalid slugs short-circuit before any network call, and every failure
 * (no session, REST unreachable, unexpected status) degrades to `unknown`
 * so the wizard fails open while provisioning still enforces uniqueness.
 */

// Mocked explicitly: the `^@lib/` moduleNameMapper outranks the shared
// server-session mock mapping, so the action would otherwise pull in next-auth.
jest.mock('@lib/auth/server-session', () => ({
  getAuthSession: jest.fn(async () => null),
}));

import { getAuthSession } from '@lib/auth/server-session';
import { checkTenantSlugAvailability } from '../../lib/auth/tenant-slug-availability';
import { REST_API_BASE_URL } from '../../lib/rest-auth';

const mockGetAuthSession = getAuthSession as jest.Mock;
const mockFetch = jest.fn<Promise<{ status: number }>, [string, RequestInit]>();

beforeEach(() => {
  jest.clearAllMocks();
  global.fetch = mockFetch as unknown as typeof fetch;
  mockGetAuthSession.mockResolvedValue({
    user: { user_id: 'user-1', email: 'user@example.com', name: 'User One' },
  });
  mockFetch.mockResolvedValue({ status: 404 });
});

describe('checkTenantSlugAvailability', () => {
  it('reports an unclaimed slug (HEAD 404) as available', async () => {
    const result = await checkTenantSlugAvailability('acme-corp');

    expect(result).toEqual({ status: 'available' });
    expect(mockFetch).toHaveBeenCalledWith(
      `${REST_API_BASE_URL}/tenants/acme-corp`,
      expect.objectContaining({ method: 'HEAD', cache: 'no-store' })
    );
  });

  it('reports an accessible existing tenant (HEAD 200) as taken', async () => {
    mockFetch.mockResolvedValue({ status: 200 });

    expect(await checkTenantSlugAvailability('acme-corp')).toEqual({ status: 'taken' });
  });

  it("reports another user's tenant (HEAD 403) as taken", async () => {
    mockFetch.mockResolvedValue({ status: 403 });

    expect(await checkTenantSlugAvailability('acme-corp')).toEqual({ status: 'taken' });
  });

  it('normalizes whitespace and case before probing', async () => {
    await checkTenantSlugAvailability('  ACME-Corp  ');

    expect(mockFetch).toHaveBeenCalledWith(
      `${REST_API_BASE_URL}/tenants/acme-corp`,
      expect.anything()
    );
  });

  it('rejects a malformed slug without any network call', async () => {
    const result = await checkTenantSlugAvailability('not a slug!');

    expect(result.status).toBe('invalid');
    expect(result.error).toMatch(/lowercase letters, numbers, and dashes/i);
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it('rejects the reserved slug "me" without any network call', async () => {
    const result = await checkTenantSlugAvailability('me');

    expect(result.status).toBe('invalid');
    expect(result.error).toMatch(/reserved/i);
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it('degrades to unknown when there is no authenticated session', async () => {
    mockGetAuthSession.mockResolvedValue(null);

    expect(await checkTenantSlugAvailability('acme-corp')).toEqual({ status: 'unknown' });
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it('degrades to unknown on an unexpected REST status', async () => {
    mockFetch.mockResolvedValue({ status: 500 });

    expect(await checkTenantSlugAvailability('acme-corp')).toEqual({ status: 'unknown' });
  });

  it('degrades to unknown when REST is unreachable, without throwing', async () => {
    const consoleError = jest.spyOn(console, 'error').mockImplementation(() => undefined);
    mockFetch.mockRejectedValue(new Error('connection refused'));

    expect(await checkTenantSlugAvailability('acme-corp')).toEqual({ status: 'unknown' });
    consoleError.mockRestore();
  });
});
