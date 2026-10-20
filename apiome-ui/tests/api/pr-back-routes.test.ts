/**
 * @jest-environment node
 *
 * The PR-back BFF routes (REPO-5.8, #2793).
 *
 * Drives the real handlers with the session, the tenant lookup and the upstream `fetch` mocked:
 * the tenant comes from the session, only whitelisted fields are forwarded, malformed requests
 * are refused before apiome-rest is called, and a refusal keeps its status and code.
 */

import { beforeEach, describe, expect, jest, test } from '@jest/globals';

jest.mock('@lib/auth/server-session', () => ({
  getAuthSession: jest.fn(),
}));

jest.mock('@lib/db/helper', () => ({
  getTenantById: jest.fn(),
}));

jest.mock('@lib/rest-auth', () => ({
  createRestAuthHeaders: jest.fn(() => ({ Authorization: 'Bearer test-token', 'Content-Type': 'application/json' })),
  REST_API_BASE_URL: 'http://rest.test/v1',
}));

import { NextRequest } from 'next/server';
import { getAuthSession } from '@lib/auth/server-session';
import { getTenantById } from '@lib/db/helper';
import { POST as syncPost } from '@/app/api/projects/[projectId]/pr-back/route';
import { GET as listGet } from '@/app/api/projects/[projectId]/pr-back/repositories/route';
import { GET as settingsGet, PUT as settingsPut } from '@/app/api/repositories/[id]/pr-back-settings/route';

const mockSession = getAuthSession as unknown as jest.Mock;
const mockTenant = getTenantById as unknown as jest.Mock;
const TENANT_ID = '550e8400-e29b-41d4-a716-446655440000';
const PROJECT_ID = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const REPO = '66666666-6666-4666-8666-666666666666';

let fetchMock: jest.Mock;

function upstream(body: unknown, status = 200): void {
  fetchMock = jest.fn(async () =>
    new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }),
  ) as unknown as jest.Mock;
  global.fetch = fetchMock as unknown as typeof fetch;
}

function lastCall(): { url: string; init: RequestInit } {
  const [url, init] = fetchMock.mock.calls.at(-1) as [string, RequestInit];
  return { url, init };
}

function jsonRequest(url: string, method: string, body: unknown): NextRequest {
  return new NextRequest(url, { method, body: JSON.stringify(body), headers: { 'Content-Type': 'application/json' } });
}

beforeEach(() => {
  mockSession.mockReset();
  mockTenant.mockReset();
  mockSession.mockResolvedValue({
    user: { user_id: 'u1', email: 'ada@acme.io', name: 'Ada', current_tenant_id: TENANT_ID },
  } as never);
  mockTenant.mockResolvedValue({ id: TENANT_ID, slug: 'acme' } as never);
});

describe('POST /api/projects/[projectId]/pr-back', () => {
  const call = (body: unknown) =>
    syncPost(jsonRequest(`http://ui.test/api/projects/${PROJECT_ID}/pr-back`, 'POST', body), {
      params: Promise.resolve({ projectId: PROJECT_ID }),
    });

  test('forwards only the whitelisted fields to the session tenant', async () => {
    upstream({ status: 'opened', pullRequestNumber: 7 });
    const response = await call({ repositoryId: REPO, version: '1.4.0', dryRun: false, extra: 'nope' });
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ success: true, status: 'opened', pullRequestNumber: 7 });
    const { url, init } = lastCall();
    expect(url).toBe(`http://rest.test/v1/tenants/acme/projects/${PROJECT_ID}/pr-back`);
    expect(init.method).toBe('POST');
    expect(JSON.parse(String(init.body))).toEqual({ repositoryId: REPO, version: '1.4.0', dryRun: false });
  });

  test('refuses a malformed body before calling apiome-rest', async () => {
    upstream({});
    const response = await call({ repositoryId: 'not-a-uuid' });
    expect(response.status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  test('keeps a refusal status and code', async () => {
    upstream({ detail: { code: 'pr-back-project-not-allowed', message: 'Shop is not on the allow list.' } }, 403);
    const response = await call({ repositoryId: REPO });
    expect(response.status).toBe(403);
    const body = (await response.json()) as { error: string; code: string };
    expect(body.code).toBe('pr-back-project-not-allowed');
    expect(body.error).toMatch(/allow list/);
  });

  test('requires a session', async () => {
    mockSession.mockResolvedValue(null as never);
    upstream({});
    expect((await call({ repositoryId: REPO })).status).toBe(401);
  });
});

describe('GET /api/projects/[projectId]/pr-back/repositories', () => {
  test('forwards to the listing', async () => {
    upstream({ projectId: PROJECT_ID, repositories: [] });
    const response = await listGet(new Request('http://ui.test/x'), { params: Promise.resolve({ projectId: PROJECT_ID }) });
    expect(response.status).toBe(200);
    expect(lastCall().url).toBe(`http://rest.test/v1/tenants/acme/projects/${PROJECT_ID}/pr-back/repositories`);
  });
});

describe('/api/repositories/[id]/pr-back-settings', () => {
  const url = `http://ui.test/api/repositories/${REPO}/pr-back-settings`;
  const params = (id = REPO) => ({ params: Promise.resolve({ id }) });

  test('GET forwards and rejects a malformed id', async () => {
    upstream({ repositoryId: REPO, configured: false });
    const response = await settingsGet(new NextRequest(url), params());
    expect(response.status).toBe(200);
    expect(lastCall().url).toBe(`http://rest.test/v1/tenants/acme/repositories/${REPO}/pr-back-settings`);
    upstream({});
    expect((await settingsGet(new NextRequest(url), params('x'))).status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  test('PUT forwards only the five settings fields', async () => {
    upstream({ repositoryId: REPO, configured: true });
    const response = await settingsPut(
      jsonRequest(url, 'PUT', {
        projectPolicy: 'deny',
        projectIds: [PROJECT_ID],
        targetBranch: 'develop',
        commitMessageTemplate: '',
        reviewers: ['octocat'],
        tenant_id: 'evil',
      }),
      params(),
    );
    expect(response.status).toBe(200);
    const { init } = lastCall();
    expect(init.method).toBe('PUT');
    expect(JSON.parse(String(init.body))).toEqual({
      projectPolicy: 'deny',
      projectIds: [PROJECT_ID],
      targetBranch: 'develop',
      commitMessageTemplate: null,
      reviewers: ['octocat'],
    });
  });

  test('PUT keeps a validation refusal', async () => {
    upstream({ detail: { code: 'pr-back-branch-invalid', message: "Target branch 'a..b': no '..'." } }, 422);
    const response = await settingsPut(jsonRequest(url, 'PUT', { targetBranch: 'a..b' }), params());
    expect(response.status).toBe(422);
    expect(((await response.json()) as { code: string }).code).toBe('pr-back-branch-invalid');
  });
});
