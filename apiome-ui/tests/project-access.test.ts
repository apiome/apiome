/**
 * authorizeProjectAction — the guard in front of the project server actions in lib/db/helper.ts.
 *
 * A server action is a public POST endpoint, so the guard must refuse an anonymous caller, a project
 * in another tenant and a caller without the `projects:<action>` grant, and must refuse when
 * apiome-rest cannot say what the caller holds (fail closed).
 */

import { describe, test, expect, jest, beforeEach } from '@jest/globals';

jest.mock('../lib/db/db', () => ({ query: jest.fn() }));
jest.mock('../lib/auth/server-session', () => ({ getAuthSession: jest.fn() }));
jest.mock('../lib/rest-auth', () => ({
  REST_API_BASE_URL: 'http://rest.test/v1',
  createRestAuthHeaders: jest.fn(() => ({ Authorization: 'Bearer test' })),
}));

import {
  authorizeProjectAction,
  PROJECT_NOT_FOUND,
  PROJECT_UNAUTHORIZED,
  projectForbidden,
} from '../lib/db/project-access';
import * as dbModule from '../lib/db/db';
import * as sessionModule from '../lib/auth/server-session';

const db = dbModule as unknown as { query: jest.Mock };
const serverSession = sessionModule as unknown as { getAuthSession: jest.Mock };
const fetchMock = jest.fn<typeof fetch>();

/** A signed-in member of tenant-1. */
function signIn() {
  serverSession.getAuthSession.mockResolvedValue({
    user: { user_id: 'user-1', email: 'member@example.com', current_tenant_id: 'tenant-1' },
  } as never);
}

/** The DB answers: the project's tenant (when looked up), then the tenant's slug. */
function stubDb(projectTenant: string | null = 'tenant-1') {
  db.query.mockImplementation(async (sql: unknown) => {
    if (String(sql).includes('FROM apiome.projects')) {
      return { rows: projectTenant ? [{ tenant_id: projectTenant }] : [] };
    }
    return { rows: [{ slug: 'acme' }] };
  });
}

/** apiome-rest answers `permissions/me` with these grants. */
function grants(body: { is_admin?: boolean; permissions?: string[] }, status = 200) {
  fetchMock.mockResolvedValue({ ok: status >= 200 && status < 300, status, json: async () => body } as Response);
}

describe('authorizeProjectAction', () => {
  beforeEach(() => {
    db.query.mockReset();
    serverSession.getAuthSession.mockReset();
    fetchMock.mockReset();
    global.fetch = fetchMock as unknown as typeof fetch;
  });

  test('refuses a caller with no session, before touching the database', async () => {
    serverSession.getAuthSession.mockResolvedValue(null as never);

    await expect(authorizeProjectAction('delete', 'proj-1')).resolves.toEqual({
      ok: false,
      error: PROJECT_UNAUTHORIZED,
    });
    expect(db.query).not.toHaveBeenCalled();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  test('refuses a session with no current workspace', async () => {
    serverSession.getAuthSession.mockResolvedValue({ user: { user_id: 'user-1' } } as never);

    await expect(authorizeProjectAction('create')).resolves.toEqual({ ok: false, error: PROJECT_UNAUTHORIZED });
  });

  test('reports a project in another tenant as not found, without asking REST', async () => {
    signIn();
    stubDb('tenant-2');

    await expect(authorizeProjectAction('edit', 'proj-1')).resolves.toEqual({ ok: false, error: PROJECT_NOT_FOUND });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  test('reports a missing project as not found', async () => {
    signIn();
    stubDb(null);

    await expect(authorizeProjectAction('delete', 'proj-gone')).resolves.toEqual({
      ok: false,
      error: PROJECT_NOT_FOUND,
    });
  });

  test('refuses a member without the grant (a viewer deleting)', async () => {
    signIn();
    stubDb();
    grants({ is_admin: false, permissions: ['projects:view'] });

    await expect(authorizeProjectAction('delete', 'proj-1')).resolves.toEqual({
      ok: false,
      error: projectForbidden('delete'),
    });
    expect(fetchMock).toHaveBeenCalledWith(
      'http://rest.test/v1/access/acme/permissions/me',
      expect.objectContaining({ cache: 'no-store' })
    );
  });

  test('allows a member holding the grant (an editor editing)', async () => {
    signIn();
    stubDb();
    grants({ is_admin: false, permissions: ['projects:view', 'projects:edit'] });

    await expect(authorizeProjectAction('edit', 'proj-1')).resolves.toEqual({
      ok: true,
      userId: 'user-1',
      tenantId: 'tenant-1',
    });
  });

  test('allows a tenant administrator whatever the grid says', async () => {
    signIn();
    stubDb();
    grants({ is_admin: true, permissions: [] });

    await expect(authorizeProjectAction('create')).resolves.toMatchObject({ ok: true });
  });

  test.each([
    ['REST answers an error status', () => grants({ is_admin: true }, 503)],
    ['REST is unreachable', () => fetchMock.mockRejectedValue(new Error('ECONNREFUSED'))],
  ])('fails closed when %s', async (_case, arrange) => {
    signIn();
    stubDb();
    arrange();

    await expect(authorizeProjectAction('create')).resolves.toEqual({ ok: false, error: projectForbidden('create') });
  });
});
