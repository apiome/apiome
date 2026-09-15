/**
 * @jest-environment node
 *
 * `/api/projects/[projectId]/comment-threads` and `/summary` (COL-1.3, #4515).
 *
 * Runs under the node environment: `next/server` needs the WHATWG `Request`/`Response` globals.
 *
 * Drives the real handlers with the session, tenant lookup, label resolver and upstream `fetch`
 * mocked, and pins: the tenant comes from the session, only the panel's filters reach apiome-rest,
 * threads come back with their anchor context (and without it when labelling fails), apiome-rest's
 * refusals keep their status, and the summary counts with the Studio's rule over every open page.
 */

import { describe, test, expect, jest, beforeEach } from '@jest/globals';

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

jest.mock('@lib/db/comment-anchor-labels', () => ({
  resolveCommentAnchorContexts: jest.fn(),
}));

import { NextRequest } from 'next/server';
import { getAuthSession } from '@lib/auth/server-session';
import { getTenantById } from '@lib/db/helper';
import { resolveCommentAnchorContexts } from '@lib/db/comment-anchor-labels';
import { GET as listThreads } from '@/app/api/projects/[projectId]/comment-threads/route';
import { GET as summarizeThreads } from '@/app/api/projects/[projectId]/comment-threads/summary/route';
import { restErrorMessage } from '@/app/api/projects/[projectId]/comment-threads/comment-threads-proxy';

const mockSession = getAuthSession as unknown as jest.Mock;
const mockTenant = getTenantById as unknown as jest.Mock;
const mockLabels = resolveCommentAnchorContexts as unknown as jest.Mock;

const PROJECT_ID = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const USER = {
  user_id: '660e8400-e29b-41d4-a716-446655440001',
  email: 'ada@acme.io',
  name: 'Ada',
  current_tenant_id: '550e8400-e29b-41d4-a716-446655440000',
};

/**
 * A REST thread row.
 *
 * @param id - Thread id.
 * @param overrides - Fields to change.
 * @returns The row.
 */
function restThread(id: string, overrides: Record<string, unknown> = {}) {
  return {
    id,
    project_id: PROJECT_ID,
    version_id: 'v-1',
    anchor_type: 'class',
    anchor_id: `c-${id}`,
    status: 'open',
    comment_count: 1,
    created_at: '2026-09-10T10:00:00Z',
    last_activity_at: '2026-09-12T10:00:00Z',
    ...overrides,
  };
}

/** A route context for the project. */
function context() {
  return { params: Promise.resolve({ projectId: PROJECT_ID }) };
}

/**
 * Build a request against one of the routes.
 *
 * @param path - The path after the project, e.g. `` or `/summary`.
 * @param query - The query string, with its `?`.
 * @returns The request.
 */
function request(path = '', query = ''): NextRequest {
  return new NextRequest(`http://localhost/api/projects/${PROJECT_ID}/comment-threads${path}${query}`);
}

/**
 * Stub upstream fetch with a responder.
 *
 * @param reply - Given the upstream URL, the status and body to answer with.
 * @returns The mock, whose calls record the URLs.
 */
function mockRest(reply: (url: URL) => { status: number; body: unknown }): jest.Mock {
  const fetchMock = jest.fn(async (input: unknown) => {
    const { status, body } = reply(new URL(String(input)));
    return {
      ok: status >= 200 && status < 300,
      status,
      text: async () => (typeof body === 'string' ? body : JSON.stringify(body)),
    };
  });
  (globalThis as { fetch?: unknown }).fetch = fetchMock;
  return fetchMock;
}

/** The URLs fetch was called with. */
function upstreamUrls(fetchMock: jest.Mock): URL[] {
  return fetchMock.mock.calls.map((call) => new URL(String((call as unknown[])[0])));
}

beforeEach(() => {
  jest.clearAllMocks();
  mockSession.mockResolvedValue({ user: USER } as never);
  mockTenant.mockResolvedValue({ id: USER.current_tenant_id, slug: 'acme' } as never);
  mockLabels.mockResolvedValue(new Map() as never);
});

describe('who is asking', () => {
  test('401 without a session', async () => {
    mockSession.mockResolvedValue(null as never);
    const fetchMock = mockRest(() => ({ status: 200, body: {} }));
    const res = await listThreads(request(), context());
    expect(res.status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  test('400 without a tenant', async () => {
    mockSession.mockResolvedValue({ user: { ...USER, current_tenant_id: undefined } } as never);
    const res = await summarizeThreads(request('/summary'), context());
    expect(res.status).toBe(400);
  });

  test('404 when the tenant is gone', async () => {
    mockTenant.mockResolvedValue(null as never);
    const res = await listThreads(request(), context());
    expect(res.status).toBe(404);
  });
});

describe('GET comment-threads', () => {
  test('forwards only the panel filters to the tenant from the session', async () => {
    const fetchMock = mockRest(() => ({
      status: 200,
      body: { threads: [], count: 0, total: 0, limit: 25, offset: 50 },
    }));
    const res = await listThreads(
      request('', '?status=resolved&anchor_type=operation&mentions_me=true&limit=25&offset=50&version=1.0.0&tenant_slug=evil'),
      context()
    );
    expect(res.status).toBe(200);
    const [url] = upstreamUrls(fetchMock);
    expect(url.origin + url.pathname).toBe(
      `http://rest.test/v1/tenants/acme/projects/${PROJECT_ID}/comment-threads`
    );
    expect(url.search).toBe('?status=resolved&anchor_type=operation&mentions_me=true&limit=25&offset=50');
    expect((fetchMock.mock.calls[0] as unknown[])[1]).toMatchObject({
      method: 'GET',
      headers: { Authorization: 'Bearer test-token' },
    });
  });

  test('adds each thread its anchor context, null when unresolved', async () => {
    mockRest(() => ({
      status: 200,
      body: { threads: [restThread('a'), restThread('b')], count: 2, total: 7, limit: 50, offset: 0 },
    }));
    mockLabels.mockResolvedValue(new Map([['class:c-a', { label: 'Customer', className: 'Customer' }]]) as never);

    const res = await listThreads(request(), context());
    const json = (await res.json()) as { success: boolean; total: number; threads: Array<Record<string, unknown>> };
    expect(json.success).toBe(true);
    expect(json.total).toBe(7);
    expect(json.threads.map((t) => t.anchor_context)).toEqual([{ label: 'Customer', className: 'Customer' }, null]);
    expect(mockLabels).toHaveBeenCalledWith(
      { tenantId: USER.current_tenant_id, projectRef: PROJECT_ID },
      expect.arrayContaining([expect.objectContaining({ id: 'a' })])
    );
  });

  test('keeps the list when labelling fails', async () => {
    const errorSpy = jest.spyOn(console, 'error').mockImplementation(() => undefined);
    mockRest(() => ({ status: 200, body: { threads: [restThread('a')], count: 1, total: 1, limit: 50, offset: 0 } }));
    mockLabels.mockRejectedValue(new Error('db down') as never);

    const res = await listThreads(request(), context());
    const json = (await res.json()) as { success: boolean; threads: Array<Record<string, unknown>> };
    expect(res.status).toBe(200);
    expect(json.threads[0].anchor_context).toBeNull();
    expect(errorSpy).toHaveBeenCalled();
    errorSpy.mockRestore();
  });

  test('passes apiome-rest refusals through with their status', async () => {
    mockRest(() => ({ status: 403, body: { detail: 'Forbidden' } }));
    let res = await listThreads(request(), context());
    expect(res.status).toBe(403);
    expect(await res.json()).toEqual({ success: false, error: 'Forbidden' });

    mockRest(() => ({
      status: 404,
      body: { detail: { code: 'comment-project-not-found', message: 'Project not found' } },
    }));
    res = await listThreads(request(), context());
    expect(res.status).toBe(404);
    expect(((await res.json()) as { error: string }).error).toBe('Project not found');
  });

  test('answers 502 for a reply it cannot read', async () => {
    mockRest(() => ({ status: 200, body: '<html>gateway</html>' }));
    const res = await listThreads(request(), context());
    expect(res.status).toBe(502);
  });

  test('answers 500 when the upstream is unreachable', async () => {
    const errorSpy = jest.spyOn(console, 'error').mockImplementation(() => undefined);
    (globalThis as { fetch?: unknown }).fetch = jest.fn(async () => {
      throw new Error('ECONNREFUSED');
    });
    const res = await listThreads(request(), context());
    expect(res.status).toBe(500);
    expect(((await res.json()) as { error: string }).error).toBe('ECONNREFUSED');
    errorSpy.mockRestore();
  });
});

describe('GET comment-threads/summary', () => {
  test('totals each status under the filters and counts open threads per element', async () => {
    const totals: Record<string, number> = { open: 3, resolved: 4, orphaned: 1 };
    const fetchMock = mockRest((url) => {
      const status = url.searchParams.get('status') ?? '';
      if (url.searchParams.get('limit') === '1') {
        return { status: 200, body: { threads: [], count: 0, total: totals[status], limit: 1, offset: 0 } };
      }
      return {
        status: 200,
        body: {
          threads: [
            restThread('a', { anchor_id: 'x' }),
            restThread('b', { anchor_id: 'x' }),
            restThread('c', { anchor_type: 'operation', anchor_id: 'y' }),
          ],
          count: 3,
          total: 3,
          limit: 200,
          offset: 0,
        },
      };
    });

    const res = await summarizeThreads(request('/summary', '?anchor_type=class&mentions_me=true&status=resolved'), context());
    const json = (await res.json()) as Record<string, unknown>;
    expect(json).toEqual({
      success: true,
      statusTotals: { open: 3, resolved: 4, orphaned: 1 },
      unresolvedTotal: 3,
      unresolvedByAnchor: { 'class:x': 2, 'operation:y': 1 },
      truncated: false,
    });

    const urls = upstreamUrls(fetchMock);
    const totalCalls = urls.filter((url) => url.searchParams.get('limit') === '1');
    expect(totalCalls.map((url) => url.searchParams.get('status')).sort()).toEqual(['open', 'orphaned', 'resolved']);
    for (const url of totalCalls) {
      expect(url.searchParams.get('anchor_type')).toBe('class');
      expect(url.searchParams.get('mentions_me')).toBe('true');
    }
    const openPages = urls.filter((url) => url.searchParams.get('limit') === '200');
    expect(openPages).toHaveLength(1);
    // The badge counts are unfiltered: no anchor_type, no mentions_me.
    expect(openPages[0].search).toBe('?status=open&limit=200&offset=0');
  });

  test('reads every open page, and says when the cap cut the count short', async () => {
    const pageOf = (offset: number, size: number, total: number) => ({
      status: 200,
      body: {
        threads: Array.from({ length: size }, (_, i) => restThread(`t${offset + i}`, { anchor_id: 'x' })),
        count: size,
        total,
        limit: 200,
        offset,
      },
    });

    let fetchMock = mockRest((url) => {
      if (url.searchParams.get('limit') === '1') return { status: 200, body: { threads: [], count: 0, total: 0, limit: 1, offset: 0 } };
      const offset = Number(url.searchParams.get('offset'));
      return offset === 0 ? pageOf(0, 200, 250) : pageOf(offset, 50, 250);
    });
    let json = (await (await summarizeThreads(request('/summary'), context())).json()) as Record<string, unknown>;
    expect(json.unresolvedByAnchor).toEqual({ 'class:x': 250 });
    expect(json.truncated).toBe(false);
    expect(
      upstreamUrls(fetchMock)
        .filter((url) => url.searchParams.get('limit') === '200')
        .map((url) => url.searchParams.get('offset'))
    ).toEqual(['0', '200']);

    fetchMock = mockRest((url) => {
      if (url.searchParams.get('limit') === '1') return { status: 200, body: { threads: [], count: 0, total: 0, limit: 1, offset: 0 } };
      return pageOf(Number(url.searchParams.get('offset')), 200, 5000);
    });
    json = (await (await summarizeThreads(request('/summary'), context())).json()) as Record<string, unknown>;
    expect(json.unresolvedTotal).toBe(5000);
    expect(json.unresolvedByAnchor).toEqual({ 'class:x': 2000 });
    expect(json.truncated).toBe(true);
    expect(upstreamUrls(fetchMock).filter((url) => url.searchParams.get('limit') === '200')).toHaveLength(10);
  });

  test('fails with apiome-rest status when a read is refused', async () => {
    mockRest(() => ({ status: 403, body: { detail: 'Forbidden' } }));
    const res = await summarizeThreads(request('/summary'), context());
    expect(res.status).toBe(403);
  });
});

describe('restErrorMessage', () => {
  test('reads string, object and validation details, then error, then the fallback', () => {
    expect(restErrorMessage({ detail: 'nope' }, 'x')).toBe('nope');
    expect(restErrorMessage({ detail: { code: 'c', message: 'Thread not found' } }, 'x')).toBe('Thread not found');
    expect(restErrorMessage({ detail: [{ loc: ['query'] }] }, 'x')).toBe('The request was not valid');
    expect(restErrorMessage({ error: 'boom' }, 'x')).toBe('boom');
    expect(restErrorMessage(null, 'fallback')).toBe('fallback');
  });
});
