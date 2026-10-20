/**
 * @jest-environment node
 *
 * The federation BFF routes (V2-REPO-8.2, #2806): the switch (GET/PUT, only `enabled` forwarded),
 * the project merge history and a repository's sync history — tenant from the session, malformed
 * requests refused before apiome-rest is called, refusals keep their status.
 */

import { beforeEach, describe, expect, jest, test } from '@jest/globals';

jest.mock('@lib/auth/server-session', () => ({ getAuthSession: jest.fn() }));
jest.mock('@lib/db/helper', () => ({ getTenantById: jest.fn() }));
jest.mock('@lib/rest-auth', () => ({
  createRestAuthHeaders: jest.fn(() => ({ Authorization: 'Bearer t', 'Content-Type': 'application/json' })),
  REST_API_BASE_URL: 'http://rest.test/v1',
}));

import { NextRequest } from 'next/server';
import { getAuthSession } from '@lib/auth/server-session';
import { getTenantById } from '@lib/db/helper';
import { GET as switchGet, PUT as switchPut } from '@/app/api/projects/[projectId]/repository-federation/route';
import { GET as projectHistory } from '@/app/api/projects/[projectId]/federation-merges/route';
import { GET as repositoryHistory } from '@/app/api/repositories/[id]/federation-merges/route';

const PROJECT = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
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

const project = { params: Promise.resolve({ projectId: PROJECT }) };

beforeEach(() => {
  (getAuthSession as unknown as jest.Mock).mockResolvedValue({
    user: { user_id: 'u1', email: 'ada@acme.io', name: 'Ada', current_tenant_id: 't1' },
  } as never);
  (getTenantById as unknown as jest.Mock).mockResolvedValue({ id: 't1', slug: 'acme' } as never);
});

describe('the federation switch', () => {
  test('GET forwards to the session tenant', async () => {
    upstream({ projectId: PROJECT, enabled: true });
    const response = await switchGet(new NextRequest('http://ui.test/x'), project);
    expect(await response.json()).toEqual({ success: true, projectId: PROJECT, enabled: true });
    expect(lastCall().url).toBe(`http://rest.test/v1/tenants/acme/projects/${PROJECT}/repository-federation`);
  });

  test('PUT forwards only `enabled`', async () => {
    upstream({ projectId: PROJECT, enabled: false });
    const request = new NextRequest('http://ui.test/x', {
      method: 'PUT',
      body: JSON.stringify({ enabled: false, tenant: 'evil' }),
    });
    const response = await switchPut(request, project);
    expect(response.status).toBe(200);
    const { init } = lastCall();
    expect(init.method).toBe('PUT');
    expect(JSON.parse(String(init.body))).toEqual({ enabled: false });
  });

  test('PUT refuses a non-boolean before calling apiome-rest', async () => {
    upstream({});
    const request = new NextRequest('http://ui.test/x', { method: 'PUT', body: JSON.stringify({ enabled: 'no' }) });
    expect((await switchPut(request, project)).status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  test('PUT keeps a refusal status', async () => {
    upstream({ detail: 'Forbidden: projects:edit' }, 403);
    const request = new NextRequest('http://ui.test/x', { method: 'PUT', body: JSON.stringify({ enabled: true }) });
    expect((await switchPut(request, project)).status).toBe(403);
  });
});

describe('the histories', () => {
  test('project history forwards', async () => {
    upstream({ merges: [] });
    const response = await projectHistory(new NextRequest('http://ui.test/x'), project);
    expect(await response.json()).toEqual({ success: true, merges: [] });
    expect(lastCall().url).toBe(`http://rest.test/v1/tenants/acme/projects/${PROJECT}/federation-merges`);
  });

  test('repository history forwards and refuses a malformed id', async () => {
    upstream({ merges: [] });
    const ok = await repositoryHistory(new NextRequest('http://ui.test/x'), { params: Promise.resolve({ id: REPO }) });
    expect(ok.status).toBe(200);
    expect(lastCall().url).toBe(`http://rest.test/v1/tenants/acme/repositories/${REPO}/federation-merges`);
    upstream({});
    const bad = await repositoryHistory(new NextRequest('http://ui.test/x'), { params: Promise.resolve({ id: 'x' }) });
    expect(bad.status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
