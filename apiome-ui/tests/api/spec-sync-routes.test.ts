/**
 * @jest-environment node
 *
 * The three-way synchronization BFF routes (GNC-2.3, #4739).
 *
 * Runs under the node environment: `next/server` needs the WHATWG `Request`/`Response` globals.
 *
 * Drives the real handlers with the session, the tenant lookup and the upstream `fetch` mocked,
 * and pins the four things this layer exists for:
 *
 * 1. **The tenant comes from the session**, never from the browser — a caller cannot merge a draft
 *    in another workspace by naming its slug.
 * 2. **Only the whitelist reaches apiome-rest.** A hand-made body carrying a token is forwarded
 *    without it, because both commits are read with a *stored* credential.
 * 3. **A refusal keeps its status, its message and its stable code**, so the panel can say
 *    something the reader can act on rather than "something went wrong".
 * 4. **A third resolution is refused here**, before a request is made at all — a conflict is
 *    settled towards the repository or towards the draft, and there is nothing else to choose.
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
import {
  GET as readSync,
  POST as computeSync,
} from '@/app/api/projects/[projectId]/bindings/sync/route';
import { POST as resolveConflict } from '@/app/api/projects/[projectId]/bindings/sync/plans/[planId]/conflicts/[conflictId]/route';

const mockSession = getAuthSession as unknown as jest.Mock;
const mockTenant = getTenantById as unknown as jest.Mock;

const TENANT_ID = '550e8400-e29b-41d4-a716-446655440000';
const PROJECT_ID = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const PLAN_ID = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const CONFLICT_ID = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
const USER = {
  user_id: '660e8400-e29b-41d4-a716-446655440001',
  email: 'ada@acme.io',
  name: 'Ada',
  current_tenant_id: TENANT_ID,
};

/** The last `fetch` this test installed, for URL and body assertions. */
let fetchMock: jest.Mock;

/**
 * Answer every upstream call with one reply.
 *
 * @param body - The JSON body.
 * @param status - The HTTP status; anything but 2xx is a refusal.
 */
function upstream(body: unknown, status = 200): void {
  fetchMock = jest.fn(async () =>
    new Response(typeof body === 'string' ? body : JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    })
  ) as unknown as jest.Mock;
  global.fetch = fetchMock as unknown as typeof fetch;
}

/** The URL the handler asked apiome-rest for. */
function calledUrl(): string {
  return String((fetchMock.mock.calls[0] as unknown[])[0]);
}

/** The body the handler forwarded, parsed. */
function calledBody(): Record<string, unknown> {
  const init = (fetchMock.mock.calls[0] as unknown[])[1] as RequestInit;
  return JSON.parse(String(init.body ?? '{}')) as Record<string, unknown>;
}

const params = Promise.resolve({ projectId: PROJECT_ID });
const conflictParams = Promise.resolve({
  projectId: PROJECT_ID,
  planId: PLAN_ID,
  conflictId: CONFLICT_ID,
});

/**
 * A request to one of the synchronization routes.
 *
 * @param path - The sub-path under `/bindings/sync`.
 * @param init - `method`, `body`, and whether to name a version.
 * @returns The request.
 */
function request(
  path = '',
  init: { method?: string; body?: unknown; version?: string | null } = {}
): NextRequest {
  const version = init.version === undefined ? '1.0.0' : init.version;
  const query = version ? `?version=${encodeURIComponent(version)}` : '';
  return new NextRequest(
    `http://ui.test/api/projects/${PROJECT_ID}/bindings/sync${path}${query}`,
    {
      method: init.method ?? 'GET',
      ...(init.body === undefined
        ? {}
        : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(init.body) }),
    }
  );
}

const DETAIL = {
  plan: { id: PLAN_ID, status: 'conflicted', conflict_count: 1, unresolved_count: 1 },
  conflicts: [{ id: CONFLICT_ID, pointer: '/info/version' }],
};

beforeEach(() => {
  jest.clearAllMocks();
  mockSession.mockResolvedValue({ user: USER });
  mockTenant.mockResolvedValue({ id: TENANT_ID, slug: 'acme' });
  upstream({ version_id: 'v1', bound: true, latest: null, history: [] });
});

describe('who is allowed to ask', () => {
  test('refuses a request with no session', async () => {
    mockSession.mockResolvedValue(null);
    expect((await readSync(request(), { params })).status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  test('refuses a session with no workspace selected', async () => {
    mockSession.mockResolvedValue({ user: { ...USER, current_tenant_id: undefined } });
    expect((await readSync(request(), { params })).status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  test('answers 404 when the session names a workspace that is gone', async () => {
    mockTenant.mockResolvedValue(null);
    expect((await readSync(request(), { params })).status).toBe(404);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  test('refuses to settle a conflict without a session', async () => {
    mockSession.mockResolvedValue(null);
    const response = await resolveConflict(
      request('/plans/x/conflicts/y', { method: 'POST', body: { resolution: 'git' } }),
      { params: conflictParams }
    );
    expect(response.status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe('naming the version', () => {
  test.each([
    ['read', () => readSync(request('', { version: null }), { params })],
    ['merge', () => computeSync(request('', { method: 'POST', version: null, body: {} }), { params })],
  ])('%s refuses a request that names no version', async (_label, call) => {
    expect((await call()).status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe('what reaches apiome-rest', () => {
  test('addresses the tenant from the session, not from the browser', async () => {
    await readSync(request(), { params });
    expect(calledUrl()).toBe(
      `http://rest.test/v1/tenants/acme/projects/${PROJECT_ID}/versions/1.0.0/binding/sync`
    );
  });

  test('never asks a cache whether a branch has moved', async () => {
    await readSync(request(), { params });
    const init = (fetchMock.mock.calls[0] as unknown[])[1] as RequestInit;
    expect(init.cache).toBe('no-store');
  });

  test('forwards only the whitelisted merge fields', async () => {
    upstream(DETAIL);
    await computeSync(
      request('', {
        method: 'POST',
        body: {
          candidate_id: ' c1 ',
          refresh: true,
          token: 'ghp_secret',
          linked_account_id: 'nope',
        },
      }),
      { params }
    );
    expect(calledBody()).toEqual({ candidate_id: 'c1', refresh: true });
  });

  test('sends an empty body when nothing was asked for', async () => {
    upstream(DETAIL);
    await computeSync(request('', { method: 'POST', body: {} }), { params });
    expect(calledBody()).toEqual({});
  });

  test('addresses a conflict under the project, by plan and conflict id', async () => {
    upstream(DETAIL);
    await resolveConflict(
      request(`/plans/${PLAN_ID}/conflicts/${CONFLICT_ID}`, {
        method: 'POST',
        body: { resolution: 'git', note: ' agreed ' },
      }),
      { params: conflictParams }
    );
    expect(calledUrl()).toBe(
      `http://rest.test/v1/tenants/acme/projects/${PROJECT_ID}` +
        `/sync-plans/${PLAN_ID}/conflicts/${CONFLICT_ID}`
    );
    expect(calledBody()).toEqual({ resolution: 'git', note: 'agreed' });
  });

  test.each([['custom'], [''], ['GIT'], ['mine']])(
    'refuses the resolution %p before a request is made',
    async (resolution) => {
      const response = await resolveConflict(
        request(`/plans/${PLAN_ID}/conflicts/${CONFLICT_ID}`, {
          method: 'POST',
          body: { resolution },
        }),
        { params: conflictParams }
      );
      expect(response.status).toBe(400);
      expect(fetchMock).not.toHaveBeenCalled();
    }
  );
});

describe('what comes back', () => {
  test('wraps a merge result in the panel envelope', async () => {
    upstream(DETAIL);
    const response = await computeSync(request('', { method: 'POST', body: {} }), { params });
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ success: true, ...DETAIL });
  });

  test.each([
    ['sync-not-bound', 404],
    ['sync-base-drifted', 409],
    ['sync-conflict-resolved', 409],
    ['binding-repository-forbidden', 403],
  ])('passes the %p refusal on with its status and code', async (code, status) => {
    upstream({ detail: { code, message: 'nope' } }, status);
    const response = await computeSync(request('', { method: 'POST', body: {} }), { params });
    expect(response.status).toBe(status);
    expect(await response.json()).toEqual({ success: false, error: 'nope', code });
  });

  test('turns an unreadable upstream reply into a 502 rather than a blank success', async () => {
    upstream('not json at all');
    const response = await readSync(request(), { params });
    expect(response.status).toBe(502);
    expect((await response.json()).success).toBe(false);
  });
});
