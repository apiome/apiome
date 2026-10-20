/**
 * @jest-environment node
 *
 * The repository-sources BFF route (REPO-5.7, #2792).
 *
 * Drives the real handler with the session, the tenant lookup and the upstream `fetch` mocked: the
 * tenant comes from the session, `?version=` is forwarded, and a refusal keeps its status.
 */

import { beforeEach, describe, expect, jest, test } from '@jest/globals';

jest.mock('@lib/auth/server-session', () => ({
  getAuthSession: jest.fn(),
}));

jest.mock('@lib/db/helper', () => ({
  getTenantById: jest.fn(),
}));

jest.mock('@lib/rest-auth', () => ({
  createRestAuthHeaders: jest.fn(() => ({ Authorization: 'Bearer test-token' })),
  REST_API_BASE_URL: 'http://rest.test/v1',
}));

import { NextRequest } from 'next/server';
import { getAuthSession } from '@lib/auth/server-session';
import { getTenantById } from '@lib/db/helper';
import { GET } from '@/app/api/projects/[projectId]/repository-sources/route';

const mockSession = getAuthSession as unknown as jest.Mock;
const mockTenant = getTenantById as unknown as jest.Mock;
const TENANT_ID = '550e8400-e29b-41d4-a716-446655440000';
const PROJECT_ID = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';

let fetchMock: jest.Mock;

function upstream(body: unknown, status = 200): void {
  fetchMock = jest.fn(async () =>
    new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }),
  ) as unknown as jest.Mock;
  global.fetch = fetchMock as unknown as typeof fetch;
}

function call(query = '') {
  return GET(new NextRequest(`http://ui.test/api/projects/${PROJECT_ID}/repository-sources${query}`), {
    params: Promise.resolve({ projectId: PROJECT_ID }),
  });
}

describe('GET /api/projects/[projectId]/repository-sources', () => {
  beforeEach(() => {
    mockSession.mockReset();
    mockTenant.mockReset();
    mockSession.mockResolvedValue({
      user: { user_id: 'u1', email: 'ada@acme.io', name: 'Ada', current_tenant_id: TENANT_ID },
    } as never);
    mockTenant.mockResolvedValue({ id: TENANT_ID, slug: 'acme' } as never);
  });

  test('forwards to the session tenant and passes the version through', async () => {
    upstream({ project_id: PROJECT_ID, sources: [], entities: [], counts: {} });
    const response = await call('?version=1.2.0');
    expect(response.status).toBe(200);
    expect(await response.json()).toMatchObject({ success: true, project_id: PROJECT_ID });
    expect(fetchMock.mock.calls[0][0]).toBe(
      `http://rest.test/v1/tenants/acme/projects/${PROJECT_ID}/repository-sources?version=1.2.0`,
    );
  });

  test('omits the version when none is given', async () => {
    upstream({ project_id: PROJECT_ID, sources: [], entities: [], counts: {} });
    await call();
    expect(fetchMock.mock.calls[0][0]).toBe(
      `http://rest.test/v1/tenants/acme/projects/${PROJECT_ID}/repository-sources`,
    );
  });

  test('a refusal keeps its status and message', async () => {
    upstream({ detail: "no project 'x' in this tenant" }, 404);
    const response = await call();
    expect(response.status).toBe(404);
    expect(await response.json()).toEqual({ success: false, error: "no project 'x' in this tenant" });
  });

  test('without a session nothing is forwarded', async () => {
    mockSession.mockResolvedValue(null as never);
    upstream({});
    const response = await call();
    expect(response.status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
