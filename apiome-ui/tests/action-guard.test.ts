/**
 * lib/auth/action-guard — the checks every server action opens with.
 *
 * Each check must refuse a signed-out caller, treat a resource outside the caller's workspaces as
 * not found, take role grants from apiome-rest and fail closed when REST cannot answer.
 */

import { describe, test, expect, jest, beforeEach } from '@jest/globals';

jest.mock('../lib/db/db', () => ({ query: jest.fn() }));
jest.mock('../lib/rest-auth', () => ({
  REST_API_BASE_URL: 'http://rest.test/v1',
  createRestAuthHeaders: jest.fn(() => ({ Authorization: 'Bearer test' })),
}));
jest.mock('next/headers', () => ({ cookies: jest.fn() }));
jest.mock('../lib/auth/admin-session', () => ({ verifyAdminSessionToken: jest.fn() }));

import * as guard from '../lib/auth/action-guard';
import * as dbModule from '../lib/db/db';
import * as sessionModule from '../lib/auth/server-session';
import * as headersModule from 'next/headers';
import * as adminSessionModule from '../lib/auth/admin-session';

const db = dbModule as unknown as { query: jest.Mock };
const session = sessionModule as unknown as { getAuthSession: jest.Mock };
const headers = headersModule as unknown as { cookies: jest.Mock };
const adminSession = adminSessionModule as unknown as { verifyAdminSessionToken: jest.Mock };
const fetchMock = jest.fn<typeof fetch>();

/** Sign in as user-1 with tenant-1 selected. */
function signIn() {
  session.getAuthSession.mockResolvedValue({ user: { user_id: 'user-1', current_tenant_id: 'tenant-1' } } as never);
}

/**
 * Answer the guard's queries: user-1 is a member of `memberOf`, an administrator of `adminOf`, and
 * resources resolve to `resourceTenant`.
 */
function stubDb({
  memberOf = ['tenant-1'],
  adminOf = [] as string[],
  resourceTenant = 'tenant-1' as string | null,
} = {}) {
  db.query.mockImplementation(async (sql: unknown, params: unknown) => {
    const text = String(sql);
    const [first] = params as unknown[];
    if (text.includes('UNION ALL')) return { rows: memberOf.includes(String(first)) ? [{ '?column?': 1 }] : [] };
    if (text.includes('FROM apiome.tenant_administrators WHERE tenant_id')) {
      return { rows: adminOf.includes(String(first)) ? [{ '?column?': 1 }] : [] };
    }
    if (text.includes('SELECT slug')) return { rows: [{ slug: 'acme' }] };
    return { rows: resourceTenant ? [{ tenant_id: resourceTenant, project_id: 'proj-1', found: 1 }] : [] };
  });
}

/** apiome-rest answers `permissions/me` with these grants. */
function grants(body: guard.TenantGrants, status = 200) {
  fetchMock.mockResolvedValue({ ok: status === 200, status, json: async () => body } as Response);
}

beforeEach(() => {
  db.query.mockReset();
  session.getAuthSession.mockReset();
  session.getAuthSession.mockResolvedValue(null as never);
  fetchMock.mockReset();
  global.fetch = fetchMock as unknown as typeof fetch;
  headers.cookies.mockReset();
  adminSession.verifyAdminSessionToken.mockReset();
});

describe('requireSelf', () => {
  test('refuses a signed-out caller', async () => {
    await expect(guard.requireSelf('user-1')).resolves.toBe(guard.UNAUTHORIZED);
  });

  test("refuses another user's id", async () => {
    signIn();
    await expect(guard.requireSelf('user-2')).resolves.toBe(guard.UNAUTHORIZED);
  });

  test('allows the caller', async () => {
    signIn();
    await expect(guard.requireSelf('user-1')).resolves.toBeNull();
  });

  test('requireSelfOrNobody allows an absent user only when signed in', async () => {
    await expect(guard.requireSelfOrNobody(undefined)).resolves.toBe(guard.UNAUTHORIZED);
    signIn();
    await expect(guard.requireSelfOrNobody(null)).resolves.toBeNull();
    await expect(guard.requireSelfOrNobody('user-2')).resolves.toBe(guard.UNAUTHORIZED);
  });
});

describe('requireTenantMember', () => {
  test('refuses a signed-out caller without querying', async () => {
    await expect(guard.requireTenantMember('tenant-1')).resolves.toBe(guard.UNAUTHORIZED);
    expect(db.query).not.toHaveBeenCalled();
  });

  test('reports a workspace the caller is not in as not found', async () => {
    signIn();
    stubDb();
    await expect(guard.requireTenantMember('tenant-2')).resolves.toBe(guard.NOT_FOUND);
  });

  test('reports an unresolved resource as not found', async () => {
    signIn();
    await expect(guard.requireTenantMember(null)).resolves.toBe(guard.NOT_FOUND);
  });

  test('allows a member', async () => {
    signIn();
    stubDb();
    await expect(guard.requireTenantMember('tenant-1')).resolves.toBeNull();
  });
});

describe('requireTenantAdmin', () => {
  test('refuses a member who is not an administrator', async () => {
    signIn();
    stubDb();
    await expect(guard.requireTenantAdmin('tenant-1')).resolves.toBe(guard.forbidden('tenant:admin'));
  });

  test('allows an administrator', async () => {
    signIn();
    stubDb({ adminOf: ['tenant-1'] });
    await expect(guard.requireTenantAdmin('tenant-1')).resolves.toBeNull();
  });

  test('says not found for a workspace the caller is not in', async () => {
    signIn();
    stubDb({ adminOf: ['tenant-2'] });
    await expect(guard.requireTenantAdmin('tenant-2')).resolves.toBe(guard.NOT_FOUND);
  });
});

describe('requireTenantPermission', () => {
  test('refuses a member without the grant', async () => {
    signIn();
    stubDb();
    grants({ is_admin: false, permissions: ['api_keys:view'] });
    await expect(guard.requireTenantPermission('tenant-1', 'api_keys:delete')).resolves.toBe(
      guard.forbidden('api_keys:delete')
    );
    expect(fetchMock).toHaveBeenCalledWith(
      'http://rest.test/v1/access/acme/permissions/me',
      expect.objectContaining({ cache: 'no-store' })
    );
  });

  test('allows a member holding the grant, and a tenant administrator', async () => {
    signIn();
    stubDb();
    grants({ permissions: ['api_keys:delete'] });
    await expect(guard.requireTenantPermission('tenant-1', 'api_keys:delete')).resolves.toBeNull();
    grants({ is_admin: true, permissions: [] });
    await expect(guard.requireTenantPermission('tenant-1', 'versions:publish')).resolves.toBeNull();
  });

  test('does not ask REST about a workspace the caller is not in', async () => {
    signIn();
    stubDb();
    await expect(guard.requireTenantPermission('tenant-2', 'api_keys:delete')).resolves.toBe(guard.NOT_FOUND);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  test.each([
    ['REST answers an error status', () => grants({ is_admin: true }, 503)],
    ['REST is unreachable', () => fetchMock.mockRejectedValue(new Error('ECONNREFUSED'))],
  ])('fails closed when %s', async (_case, arrange) => {
    signIn();
    stubDb();
    arrange();
    await expect(guard.requireTenantPermission('tenant-1', 'projects:create')).resolves.toBe(
      guard.forbidden('projects:create')
    );
  });
});

describe('requireSuperAdmin', () => {
  test('allows a verified admin_session cookie', async () => {
    headers.cookies.mockResolvedValue({ get: () => ({ value: 'signed' }) } as never);
    adminSession.verifyAdminSessionToken.mockReturnValue(true as never);
    await expect(guard.requireSuperAdmin()).resolves.toBeNull();
  });

  test('refuses a missing or forged cookie — a user session is not enough', async () => {
    signIn();
    headers.cookies.mockResolvedValue({ get: () => undefined } as never);
    adminSession.verifyAdminSessionToken.mockReturnValue(false as never);
    await expect(guard.requireSuperAdmin()).resolves.toBe(guard.UNAUTHORIZED);
  });

  test('refuses when cookies cannot be read', async () => {
    headers.cookies.mockRejectedValue(new Error('outside a request') as never);
    await expect(guard.requireSuperAdmin()).resolves.toBe(guard.UNAUTHORIZED);
  });
});

describe('tenant resolvers', () => {
  test('resolve a resource to its workspace', async () => {
    stubDb({ resourceTenant: 'tenant-9' });
    await expect(guard.tenantOfVersion('v-1')).resolves.toBe('tenant-9');
    await expect(guard.tenantOfApiKey('k-1')).resolves.toBe('tenant-9');
    await expect(guard.versionScope('v-1')).resolves.toEqual({ tenantId: 'tenant-9', projectId: 'proj-1' });
  });

  test('resolve a missing, empty or malformed id to null', async () => {
    stubDb({ resourceTenant: null });
    await expect(guard.tenantOfClass('c-gone')).resolves.toBeNull();
    await expect(guard.tenantOfProject('')).resolves.toBeNull();
    await expect(guard.tenantOfMemberRecord(42)).resolves.toBeNull();
    db.query.mockRejectedValue(new Error('invalid input syntax for type uuid') as never);
    await expect(guard.tenantOfAdministratorRecord('not-a-uuid')).resolves.toBeNull();
  });

  test('tenantOfClasses needs every class found, all in one workspace', async () => {
    db.query.mockResolvedValue({ rows: [{ tenant_id: 'tenant-1', found: 2 }] } as never);
    await expect(guard.tenantOfClasses(['c-1', 'c-2'])).resolves.toBe('tenant-1');
    db.query.mockResolvedValue({ rows: [{ tenant_id: 'tenant-1', found: 1 }] } as never);
    await expect(guard.tenantOfClasses(['c-1', 'c-missing'])).resolves.toBeNull();
    db.query.mockResolvedValue({
      rows: [
        { tenant_id: 'tenant-1', found: 2 },
        { tenant_id: 'tenant-2', found: 2 },
      ],
    } as never);
    await expect(guard.tenantOfClasses(['c-1', 'c-other'])).resolves.toBeNull();
    await expect(guard.tenantOfClasses([])).resolves.toBeNull();
    await expect(guard.tenantOfClasses('c-1')).resolves.toBeNull();
  });
});
