/**
 * @jest-environment node
 *
 * The stored overlay chain BFF routes — GVM-4.3 (#5878).
 *
 * Drives the real handlers with the session, the tenant lookup and the upstream `fetch` mocked:
 *
 * 1. **The tenant comes from the session**; `projectId` is required.
 * 2. **Each route reaches the right apiome-rest path and verb**, ids encoded.
 * 3. **A refusal keeps its status and its stable code** (`overlay-version-published`).
 * 4. The enrichment overlay route reaches AGX-1.3's `…/enrichment/overlay`.
 */

import { beforeEach, describe, expect, jest, test } from '@jest/globals';

jest.mock('@lib/auth/server-session', () => ({
  getAuthSession: jest.fn(),
}));

jest.mock('@lib/db/helper', () => ({
  getTenantById: jest.fn(),
}));

jest.mock('@lib/rest-auth', () => ({
  createRestAuthHeaders: jest.fn(() => ({
    'Content-Type': 'application/json',
    Authorization: 'Bearer test-token',
  })),
  REST_API_BASE_URL: 'http://rest.test/v1',
}));

import { NextRequest } from 'next/server';
import { getAuthSession } from '@lib/auth/server-session';
import { getTenantById } from '@lib/db/helper';
import { GET as listChain, POST as addOverlay } from '@/app/api/versions/[versionId]/overlays/route';
import { GET as preview } from '@/app/api/versions/[versionId]/overlays/preview/route';
import {
  DELETE as removeOverlay,
  PUT as replaceOverlay,
} from '@/app/api/versions/[versionId]/overlays/[overlayId]/route';
import { GET as enrichmentOverlay } from '@/app/api/agent-access/toolsets/[toolsetId]/enrichment-overlay/route';

const mockSession = getAuthSession as unknown as jest.Mock;
const mockTenant = getTenantById as unknown as jest.Mock;

const USER = { user_id: 'u-1', email: 'ada@acme.io', name: 'Ada', current_tenant_id: 't-1' };
const VERSION = 'rev 1';

let fetchMock: jest.Mock;

/** Answer every upstream call with one reply. */
function upstream(body: unknown, status = 200): void {
  fetchMock = jest.fn(async () =>
    status === 204
      ? new Response(null, { status })
      : new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
  ) as unknown as jest.Mock;
  global.fetch = fetchMock as unknown as typeof fetch;
}

/** The URL and method of the upstream call. */
function called(): { url: string; method: string; body: unknown } {
  const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
  return { url, method: init.method ?? 'GET', body: init.body ? JSON.parse(String(init.body)) : undefined };
}

function request(url: string, method = 'GET', body?: unknown): NextRequest {
  return new NextRequest(`http://ui.test${url}`, {
    method,
    body: body === undefined ? undefined : JSON.stringify(body),
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
  });
}

const params = <T extends Record<string, string>>(value: T) => ({ params: Promise.resolve(value) });

beforeEach(() => {
  mockSession.mockReset();
  mockTenant.mockReset();
  (mockSession as jest.Mock<() => Promise<unknown>>).mockResolvedValue({ user: USER });
  (mockTenant as jest.Mock<() => Promise<unknown>>).mockResolvedValue({ id: 't-1', slug: 'acme' });
});

describe('overlay chain routes', () => {
  test('list reaches the revision chain for the session tenant', async () => {
    upstream({ overlays: [] });
    const response = await listChain(request('/api/versions/x/overlays?projectId=p-1'), params({ versionId: VERSION }));
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ success: true, data: { overlays: [] } });
    expect(called()).toMatchObject({ url: 'http://rest.test/v1/versions/acme/p-1/rev%201/overlays', method: 'GET' });
  });

  test('projectId is required', async () => {
    upstream({});
    const response = await listChain(request('/api/versions/x/overlays'), params({ versionId: VERSION }));
    expect(response.status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  test('no session is 401 and reaches nothing', async () => {
    (mockSession as jest.Mock<() => Promise<unknown>>).mockResolvedValue(null);
    upstream({});
    const response = await listChain(request('/api/versions/x/overlays?projectId=p-1'), params({ versionId: VERSION }));
    expect(response.status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  test('add posts the body; preview, replace and remove reach their paths', async () => {
    const body = { name: 'a', source: 'manual', document: { overlay: '1.0.0' } };
    upstream({ id: 'ov-1' }, 201);
    expect((await addOverlay(request('/x?projectId=p-1', 'POST', body), params({ versionId: VERSION }))).status).toBe(201);
    expect(called()).toEqual({ url: 'http://rest.test/v1/versions/acme/p-1/rev%201/overlays', method: 'POST', body });

    upstream({ document: {} });
    await preview(request('/x?projectId=p-1'), params({ versionId: VERSION }));
    expect(called().url).toBe('http://rest.test/v1/versions/acme/p-1/rev%201/overlays/preview');

    upstream({ id: 'ov-2' });
    await replaceOverlay(request('/x?projectId=p-1', 'PUT', body), params({ versionId: VERSION, overlayId: 'ov/1' }));
    expect(called()).toMatchObject({ url: 'http://rest.test/v1/versions/acme/p-1/rev%201/overlays/ov%2F1', method: 'PUT' });

    upstream(null, 204);
    const removed = await removeOverlay(request('/x?projectId=p-1', 'DELETE'), params({ versionId: VERSION, overlayId: 'ov-1' }));
    expect(removed.status).toBe(200);
    expect(called().method).toBe('DELETE');
  });

  test('a refusal keeps its status and code', async () => {
    upstream({ detail: { code: 'overlay-version-published', message: 'This revision is published.' } }, 409);
    const response = await removeOverlay(request('/x?projectId=p-1', 'DELETE'), params({ versionId: VERSION, overlayId: 'ov-1' }));
    expect(response.status).toBe(409);
    expect(await response.json()).toMatchObject({ success: false, code: 'overlay-version-published' });
  });
});

describe('enrichment overlay route', () => {
  test('reaches the toolset enrichment overlay', async () => {
    upstream({ action_count: 1 });
    const response = await enrichmentOverlay(request('/x'), params({ toolsetId: 'ts 1' }));
    expect(response.status).toBe(200);
    expect(called().url).toBe('http://rest.test/v1/tenants/acme/agent-toolsets/ts%201/enrichment/overlay');
  });
});
