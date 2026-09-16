/**
 * @jest-environment node
 *
 * The branch-to-draft binding BFF routes (GNC-2.1, #4737).
 *
 * Runs under the node environment: `next/server` needs the WHATWG `Request`/`Response` globals.
 *
 * Drives the real handlers with the session, the tenant lookup and the upstream `fetch` mocked,
 * and pins the four things this layer exists for:
 *
 * 1. **The tenant comes from the session**, never from the browser — a caller cannot bind a draft
 *    in another workspace by naming its slug.
 * 2. **Only the whitelist reaches apiome-rest.** A hand-made body carrying a token is forwarded
 *    without it, because a private repository is read with a *stored* credential.
 * 3. **A refusal keeps its status, its message and its stable code**, so the panel can say
 *    something the reader can act on rather than "something went wrong".
 * 4. **A settlement only a system records is refused here**, before a request is made at all.
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
  DELETE as releaseBinding,
  GET as readBinding,
  POST as bindVersion,
} from '@/app/api/projects/[projectId]/bindings/route';
import { POST as checkBinding } from '@/app/api/projects/[projectId]/bindings/check/route';
import { POST as resolveCandidate } from '@/app/api/projects/[projectId]/bindings/candidates/[candidateId]/route';
import { restErrorDetail } from '@/app/api/projects/[projectId]/bindings/bindings-proxy';

const mockSession = getAuthSession as unknown as jest.Mock;
const mockTenant = getTenantById as unknown as jest.Mock;

const TENANT_ID = '550e8400-e29b-41d4-a716-446655440000';
const PROJECT_ID = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const CANDIDATE_ID = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
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

/** The route parameters the handlers take. */
const params = Promise.resolve({ projectId: PROJECT_ID });
const candidateParams = Promise.resolve({ projectId: PROJECT_ID, candidateId: CANDIDATE_ID });

/**
 * A request to one of the binding routes.
 *
 * @param path - The sub-path under `/bindings`.
 * @param init - `method`, `body`, and whether to name a version.
 * @returns The request.
 */
function request(
  path = '',
  init: { method?: string; body?: unknown; version?: string | null } = {}
): NextRequest {
  const version = init.version === undefined ? '1.0.0' : init.version;
  const query = version ? `?version=${encodeURIComponent(version)}` : '';
  return new NextRequest(`http://ui.test/api/projects/${PROJECT_ID}/bindings${path}${query}`, {
    method: init.method ?? 'GET',
    ...(init.body === undefined
      ? {}
      : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(init.body) }),
  });
}

const DETAIL = {
  binding: { id: 'b1', version_id: 'v1', ref: 'main', commit_sha: 'a'.repeat(40) },
  pending: [],
  history: [],
};

beforeEach(() => {
  jest.clearAllMocks();
  mockSession.mockResolvedValue({ user: USER });
  mockTenant.mockResolvedValue({ id: TENANT_ID, slug: 'acme' });
  upstream({ version_id: 'v1', bound: false, binding: null, released: [] });
});

describe('who is allowed to ask', () => {
  test('refuses a request with no session', async () => {
    mockSession.mockResolvedValue(null);
    const response = await readBinding(request(), { params });
    expect(response.status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  test('refuses a session with no workspace selected', async () => {
    mockSession.mockResolvedValue({ user: { ...USER, current_tenant_id: undefined } });
    const response = await readBinding(request(), { params });
    expect(response.status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  test('answers 404 when the session names a workspace that is gone', async () => {
    mockTenant.mockResolvedValue(null);
    const response = await readBinding(request(), { params });
    expect(response.status).toBe(404);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  test('addresses the tenant from the session, not from the browser', async () => {
    await readBinding(request(), { params });
    expect(calledUrl()).toBe(
      `http://rest.test/v1/tenants/acme/projects/${PROJECT_ID}/versions/1.0.0/binding`
    );
  });
});

describe('naming the version', () => {
  test.each([
    ['read', () => readBinding(request('', { version: null }), { params })],
    ['bind', () => bindVersion(request('', { method: 'POST', version: null, body: {} }), { params })],
    ['release', () => releaseBinding(request('', { method: 'DELETE', version: null }), { params })],
    ['check', () => checkBinding(request('/check', { method: 'POST', version: null }), { params })],
  ])('%s refuses a request that names no version', async (_label, call) => {
    const response = await call();
    expect(response.status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe('what reaches apiome-rest', () => {
  test('forwards only the whitelisted bind fields', async () => {
    upstream(DETAIL, 201);
    await bindVersion(
      request('', {
        method: 'POST',
        body: {
          repository_id: 'r1',
          ref: '  main  ',
          path: 'spec',
          replace: true,
          // Neither of these is a field apiome-rest accepts; forwarding either would turn the
          // panel's request into a 422 it cannot explain — and one of them is a secret.
          token: 'ghp_secret',
          tenant_slug: 'someone-else',
        },
      }),
      { params }
    );
    expect(calledBody()).toEqual({ repository_id: 'r1', ref: 'main', path: 'spec', replace: true });
  });

  test('drops replace unless it is really true', async () => {
    upstream(DETAIL, 201);
    await bindVersion(
      request('', { method: 'POST', body: { repository_id: 'r1', replace: 'yes' } }),
      { params }
    );
    expect(calledBody()).toEqual({ repository_id: 'r1' });
  });

  test('a check carries no body', async () => {
    upstream(DETAIL);
    await checkBinding(request('/check', { method: 'POST' }), { params });
    expect(calledUrl()).toContain('/binding/check');
    const init = (fetchMock.mock.calls[0] as unknown[])[1] as RequestInit;
    expect(init.body).toBeUndefined();
    expect(init.method).toBe('POST');
  });

  test('a release is a DELETE on the binding itself', async () => {
    upstream({ id: 'b1', active: false });
    await releaseBinding(request('', { method: 'DELETE' }), { params });
    const init = (fetchMock.mock.calls[0] as unknown[])[1] as RequestInit;
    expect(init.method).toBe('DELETE');
    expect(calledUrl()).toMatch(/\/binding$/);
  });

  test('forwards a settlement with its note', async () => {
    upstream(DETAIL);
    await resolveCandidate(
      request(`/candidates/${CANDIDATE_ID}`, {
        method: 'POST',
        body: { status: 'applied', note: '  merged by hand  ', to_digest: 'sha256:forged' },
      }),
      { params: candidateParams }
    );
    expect(calledUrl()).toContain(`/binding/candidates/${CANDIDATE_ID}`);
    expect(calledBody()).toEqual({ status: 'applied', note: 'merged by hand' });
  });

  test.each(['superseded', 'pending', 'anything'])(
    'refuses to settle a candidate as %s before asking apiome-rest',
    async (status) => {
      const response = await resolveCandidate(
        request(`/candidates/${CANDIDATE_ID}`, { method: 'POST', body: { status } }),
        { params: candidateParams }
      );
      expect(response.status).toBe(400);
      expect(fetchMock).not.toHaveBeenCalled();
    }
  );
});

describe('what comes back', () => {
  test('a refusal keeps its status, its message and its stable code', async () => {
    upstream({ detail: { code: 'binding-already-bound', message: 'already bound' } }, 409);
    const response = await bindVersion(
      request('', { method: 'POST', body: { repository_id: 'r1' } }),
      { params }
    );
    expect(response.status).toBe(409);
    await expect(response.json()).resolves.toEqual({
      success: false,
      error: 'already bound',
      code: 'binding-already-bound',
    });
  });

  test('a repository the credential cannot read keeps its 403', async () => {
    upstream({ detail: { code: 'binding-repository-forbidden', message: 'no access' } }, 403);
    const response = await bindVersion(
      request('', { method: 'POST', body: { repository_id: 'r1' } }),
      { params }
    );
    expect(response.status).toBe(403);
  });

  test('an unreadable reply is a 502', async () => {
    fetchMock = jest.fn(async () => new Response('<html>nope</html>', { status: 200 })) as unknown as jest.Mock;
    global.fetch = fetchMock as unknown as typeof fetch;
    const response = await readBinding(request(), { params });
    expect(response.status).toBe(502);
  });

  test('a successful read is wrapped in the success envelope', async () => {
    upstream({ version_id: 'v1', bound: true, binding: DETAIL, released: [] });
    const response = await readBinding(request(), { params });
    await expect(response.json()).resolves.toMatchObject({ success: true, bound: true });
  });
});

describe('restErrorDetail', () => {
  test.each([
    [{ detail: { code: 'binding-unchanged', message: 'still there' } }, 'still there', 'binding-unchanged'],
    [{ detail: 'plain' }, 'plain', null],
    [{ detail: [{ loc: ['body'] }] }, 'The request was not valid', null],
    [{ error: 'from the edge' }, 'from the edge', null],
    [null, 'fallback', null],
  ])('reads %p', (payload, message, code) => {
    expect(restErrorDetail(payload, 'fallback')).toEqual({ message, code });
  });
});
