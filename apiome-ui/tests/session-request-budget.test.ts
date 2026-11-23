/**
 * DBP-1.15 (#7198): one request resolves the session and the caller's memberships at most once.
 *
 * Exercises the real `getAuthSession` (`lib/auth/server-session.ts`), the action guard
 * (`lib/auth/action-guard.ts`) and the project guard (`lib/db/project-access.ts`) against one fake
 * request — a stable `headers()` object and a cookie jar — and counts what reached Better Auth, the
 * database and apiome-rest.
 */

import { describe, test, expect, jest, beforeEach } from '@jest/globals';

const mockGetSession = jest.fn<(...args: unknown[]) => Promise<unknown>>();
let mockRequestHeaders: Headers | null = new Headers();
let mockCookieText = 'better-auth.session_token=abc';

jest.mock('next/headers', () => ({
  headers: jest.fn(async () => {
    if (!mockRequestHeaders) throw new Error('outside a request');
    return mockRequestHeaders;
  }),
  cookies: jest.fn(async () => ({ toString: () => mockCookieText, get: () => undefined })),
}));
jest.mock('../lib/auth/auth', () => ({ auth: { api: { getSession: mockGetSession } } }));
jest.mock('../lib/auth/post-login-routing', () => ({ resolveActiveTenantForLogin: jest.fn() }));
jest.mock('../lib/auth/last-active-tenant', () => ({ readLastActiveTenantId: jest.fn() }));
jest.mock('../lib/db/db', () => ({ query: jest.fn() }));
jest.mock('../lib/rest-auth', () => ({
  REST_API_BASE_URL: 'http://rest.test/v1',
  createRestAuthHeaders: jest.fn(() => ({ Authorization: 'Bearer test' })),
}));
jest.mock('../lib/auth/admin-session', () => ({ verifyAdminSessionToken: jest.fn() }));
// The guard imports `../auth/server-session`, which jest maps to a stub; use the real reader.
jest.mock('../lib/auth/server-session', () => jest.requireActual('@lib/auth/server-session'));

import * as guard from '../lib/auth/action-guard';
import { authorizeProjectAction } from '../lib/db/project-access';
import { getAuthSession } from '@lib/auth/server-session';
import * as shape from '@lib/auth/better-auth-session-shape';
import * as dbModule from '../lib/db/db';
import * as postLoginModule from '../lib/auth/post-login-routing';

const db = dbModule as unknown as { query: jest.Mock };
const fetchMock = jest.fn<typeof fetch>();

/** Better Auth answers as the `customSession` plugin shapes it: tenant already derived. */
function signedIn() {
  mockGetSession.mockResolvedValue({
    user: { id: 'user-1', user_id: 'user-1', email: 'a@b.co', current_tenant_id: 'tenant-1' },
    session: { expiresAt: new Date('2030-01-01T00:00:00Z') },
  });
}

/** Count statements by kind. */
function statementsMatching(fragment: string): number {
  return db.query.mock.calls.filter(([sql]) => String(sql).includes(fragment)).length;
}

beforeEach(() => {
  mockGetSession.mockReset();
  db.query.mockReset();
  fetchMock.mockReset();
  mockRequestHeaders = new Headers();
  mockCookieText = 'better-auth.session_token=abc';
  global.fetch = fetchMock as unknown as typeof fetch;
  db.query.mockImplementation(async (sql: unknown) => {
    const text = String(sql);
    if (text.includes('UNION ALL')) return { rows: [{ '?column?': 1 }] };
    if (text.includes('SELECT slug')) return { rows: [{ slug: 'acme' }] };
    if (text.includes('tenant_administrators WHERE tenant_id')) return { rows: [{ '?column?': 1 }] };
    return { rows: [{ tenant_id: 'tenant-1' }] };
  });
  fetchMock.mockResolvedValue({ ok: true, status: 200, json: async () => ({ permissions: ['projects:edit', 'api_keys:delete'] }) } as Response);
});

describe('per-request budget', () => {
  test('a request with several guarded checks reads the session, membership, slug and grants once', async () => {
    signedIn();
    const resolveTenant = (postLoginModule as unknown as { resolveActiveTenantForLogin: jest.Mock })
      .resolveActiveTenantForLogin;
    resolveTenant.mockClear();

    expect(await guard.requireSignedIn()).toBeNull();
    expect(await guard.requireTenantMember('tenant-1')).toBeNull();
    expect(await guard.requireTenantPermission('tenant-1', 'api_keys:delete')).toBeNull();
    expect(await guard.requireTenantPermission('tenant-1', 'projects:edit')).toBeNull();
    expect(await guard.requireTenantAdmin('tenant-1')).toBeNull();
    expect((await authorizeProjectAction('edit', 'project-1')).ok).toBe(true);
    await getAuthSession();

    expect(mockGetSession).toHaveBeenCalledTimes(1);
    // The tenant came from `customSession`; the membership derivation did not run again.
    expect(resolveTenant).not.toHaveBeenCalled();
    expect(statementsMatching('UNION ALL')).toBe(1);
    expect(statementsMatching('SELECT slug')).toBe(1);
    expect(statementsMatching('tenant_administrators WHERE tenant_id = $1 AND user_id = $2 LIMIT 1')).toBe(1);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  test('a new request reads everything again', async () => {
    signedIn();
    await guard.requireTenantPermission('tenant-1', 'projects:edit');
    mockRequestHeaders = new Headers();
    await guard.requireTenantPermission('tenant-1', 'projects:edit');

    expect(mockGetSession).toHaveBeenCalledTimes(2);
    expect(statementsMatching('UNION ALL')).toBe(2);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  test('a cookie change inside the request (sign-in, tenant switch) is not served a stale session', async () => {
    mockGetSession.mockResolvedValueOnce(null);
    expect(await getAuthSession()).toBeNull();
    mockCookieText = 'better-auth.session_token=new';
    signedIn();
    expect((await getAuthSession())?.user.user_id).toBe('user-1');
    expect(mockGetSession).toHaveBeenCalledTimes(2);
  });

  test('a failed read is not kept: the next ask in the request retries', async () => {
    mockGetSession.mockRejectedValueOnce(new Error('db down'));
    await expect(getAuthSession()).rejects.toThrow('db down');
    signedIn();
    expect((await getAuthSession())?.user.user_id).toBe('user-1');
  });

  test('outside a request nothing is memoized', async () => {
    mockRequestHeaders = null;
    db.query.mockClear();
    expect(await guard.tenantSlug('tenant-1')).toBe('acme');
    expect(await guard.tenantSlug('tenant-1')).toBe('acme');
    expect(statementsMatching('SELECT slug')).toBe(2);
  });

  test('without the customSession marker the tenant is derived once, as before', async () => {
    mockGetSession.mockResolvedValue({
      user: { id: 'user-1', email: 'a@b.co' },
      session: { expiresAt: new Date('2030-01-01T00:00:00Z') },
    });
    const toAppSession = jest.spyOn(shape, 'toAppSession');
    await getAuthSession();
    expect(toAppSession).toHaveBeenCalledWith(expect.objectContaining({ id: 'user-1' }), expect.any(Date));
    toAppSession.mockRestore();
  });
});
