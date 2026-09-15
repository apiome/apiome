/**
 * @jest-environment node
 *
 * `/api/reviews/[reviewId]`, `/decision`, `/changes` and `/spec` (COL-2.2, #4518).
 *
 * Runs under the node environment: `next/server` needs the WHATWG `Request`/`Response` globals.
 *
 * Drives the real handlers with the session, tenant lookup, review-project lookup, document builder
 * and upstream `fetch` mocked, and pins:
 *
 * - the tenant comes from the session and the project from the tenant-bound lookup — a review of
 *   another tenant is a 404 before apiome-rest is asked anything;
 * - the review is read from apiome-rest before any other work, so its access check comes first;
 * - a change request without a note is refused by the route itself;
 * - apiome-rest's refusals keep their status and `review-*` code, with a reviewer-facing message;
 * - the Changes tab compares with the newest published revision (never the one under review), says
 *   so when nothing is published, and falls back to `classifiedError` when classification fails;
 * - documents are built only for revisions apiome-rest listed for the review's project.
 */

import { describe, test, expect, jest, beforeEach } from '@jest/globals';

jest.mock('@lib/auth/server-session', () => ({
  getAuthSession: jest.fn(),
}));

jest.mock('@lib/db/helper', () => ({
  getTenantById: jest.fn(),
  buildOpenApiSpecJsonForVersion: jest.fn(),
}));

jest.mock('@lib/rest-auth', () => ({
  createRestAuthHeaders: jest.fn(() => ({
    'Content-Type': 'application/json',
    Authorization: 'Bearer test-token',
  })),
  REST_API_BASE_URL: 'http://rest.test/v1',
}));

jest.mock('@lib/db/review-project', () => ({
  resolveReviewProject: jest.fn(),
}));

import { NextRequest } from 'next/server';
import { getAuthSession } from '@lib/auth/server-session';
import { buildOpenApiSpecJsonForVersion, getTenantById } from '@lib/db/helper';
import { resolveReviewProject } from '@lib/db/review-project';
import { GET as readReview } from '@/app/api/reviews/[reviewId]/route';
import { POST as decide } from '@/app/api/reviews/[reviewId]/decision/route';
import { GET as readChanges } from '@/app/api/reviews/[reviewId]/changes/route';
import { GET as readSpec } from '@/app/api/reviews/[reviewId]/spec/route';

const mockSession = getAuthSession as unknown as jest.Mock;
const mockTenant = getTenantById as unknown as jest.Mock;
const mockProject = resolveReviewProject as unknown as jest.Mock;
const mockBuildSpec = buildOpenApiSpecJsonForVersion as unknown as jest.Mock;

const REVIEW_ID = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const PROJECT_ID = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const HEAD = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
const OLD_BASE = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd';
const NEW_BASE = 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee';
const USER = {
  user_id: '660e8400-e29b-41d4-a716-446655440001',
  email: 'ravi@acme.io',
  name: 'Ravi',
  current_tenant_id: '550e8400-e29b-41d4-a716-446655440000',
};
const PROJECT = { id: PROJECT_ID, name: 'Pets API', slug: 'pets', metadata: { contact: 'team@acme.io' } };

const REVIEW_PATH = `/v1/tenants/acme/projects/${PROJECT_ID}/reviews/${REVIEW_ID}`;
const VERSIONS_PATH = `/v1/versions/acme/${PROJECT_ID}`;
const CLASSIFIED_PATH = '/v1/diff/acme/classified';

/** The review apiome-rest returns. */
function restReview(overrides: Record<string, unknown> = {}) {
  return {
    review: {
      id: REVIEW_ID,
      project_id: PROJECT_ID,
      version_id: HEAD,
      version_label: '2.0.0',
      state: 'in_review',
      round: 1,
      ...overrides,
    },
    reviewers: [{ id: 'row-1', user_id: USER.user_id, decision: 'pending' }],
    history: [],
    spec_changed: false,
  };
}

/** The project's revisions apiome-rest lists. */
const REVISIONS = [
  { id: HEAD, version_id: '2.0.0', published: false, created_at: '2026-09-01T00:00:00Z', shortMessage: 'Adds owners' },
  { id: OLD_BASE, version_id: '1.0.0', published: true, published_at: '2026-01-01T00:00:00Z' },
  { id: NEW_BASE, version_id: '1.1.0', published: true, published_at: '2026-06-01T00:00:00Z' },
];

type Reply = { status: number; body: unknown };

/**
 * Stub upstream fetch with a responder.
 *
 * @param reply - Given the URL and request init, the status and JSON body to answer with.
 * @returns The mock.
 */
function mockRest(reply: (url: URL, init?: RequestInit) => Reply): jest.Mock {
  const fetchMock = jest.fn(async (input: unknown, init?: RequestInit) => {
    const { status, body } = reply(new URL(String(input)), init);
    const text = JSON.stringify(body);
    return {
      ok: status >= 200 && status < 300,
      status,
      headers: { get: (name: string) => (name.toLowerCase() === 'content-type' ? 'application/json' : null) },
      json: async () => JSON.parse(text),
      text: async () => text,
    };
  });
  (globalThis as { fetch?: unknown }).fetch = fetchMock;
  return fetchMock;
}

/**
 * A responder serving the review, the revisions and the classifier.
 *
 * @param overrides - Replies by pathname that take precedence.
 * @returns The responder.
 */
function restStack(overrides: Record<string, Reply> = {}) {
  return (url: URL): Reply => {
    if (overrides[url.pathname]) return overrides[url.pathname];
    if (url.pathname === REVIEW_PATH) return { status: 200, body: restReview() };
    if (url.pathname === VERSIONS_PATH) return { status: 200, body: REVISIONS };
    if (url.pathname === CLASSIFIED_PATH) {
      return {
        status: 200,
        body: {
          changes: [{ ruleId: 'schema-added', severity: 'non-breaking', pointer: '/components/schemas/Owner' }],
          counts: { breaking: 0, 'non-breaking': 1, 'docs-only': 0, unclassified: 0, total: 1 },
          maxSeverity: 'non-breaking',
        },
      };
    }
    return { status: 404, body: { detail: `unrouted ${url.pathname}` } };
  };
}

/** The pathnames fetch was called with, in order. */
function upstreamPaths(fetchMock: jest.Mock): string[] {
  return fetchMock.mock.calls.map((call) => new URL(String((call as unknown[])[0])).pathname);
}

/** A route context for the review. */
function context() {
  return { params: Promise.resolve({ reviewId: REVIEW_ID }) };
}

/**
 * A request against one of the routes.
 *
 * @param path - The path after the review, e.g. `` or `/spec?side=base`.
 * @param body - A JSON body, which makes it a POST.
 * @returns The request.
 */
function request(path = '', body?: unknown): NextRequest {
  const url = `http://localhost/api/reviews/${REVIEW_ID}${path}`;
  if (body === undefined) return new NextRequest(url);
  return new NextRequest(url, {
    method: 'POST',
    body: typeof body === 'string' ? body : JSON.stringify(body),
    headers: { 'Content-Type': 'application/json' },
  });
}

beforeEach(() => {
  jest.clearAllMocks();
  mockSession.mockResolvedValue({ user: USER } as never);
  mockTenant.mockResolvedValue({ id: USER.current_tenant_id, slug: 'acme' } as never);
  mockProject.mockResolvedValue(PROJECT as never);
  mockBuildSpec.mockResolvedValue('{"openapi":"3.1.0"}' as never);
});

describe('who is asking about which review', () => {
  test('401 without a session, before any lookup', async () => {
    mockSession.mockResolvedValue(null as never);
    const fetchMock = mockRest(restStack());
    const res = await readReview(request(), context());
    expect(res.status).toBe(401);
    expect(mockProject).not.toHaveBeenCalled();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  test("404 review-not-found for a review outside the session's tenant", async () => {
    mockProject.mockResolvedValue(null as never);
    const fetchMock = mockRest(restStack());
    const res = await readChanges(request('/changes'), context());
    expect(res.status).toBe(404);
    expect(await res.json()).toEqual({ success: false, error: 'Review not found', code: 'review-not-found' });
    expect(mockProject).toHaveBeenCalledWith(REVIEW_ID, USER.current_tenant_id);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe('GET /api/reviews/[reviewId]', () => {
  test('answers the review, its project and the viewer', async () => {
    const fetchMock = mockRest(restStack());
    const res = await readReview(request(), context());
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({
      success: true,
      review: restReview(),
      project: { id: PROJECT_ID, name: 'Pets API', slug: 'pets' },
      viewerId: USER.user_id,
    });
    expect(upstreamPaths(fetchMock)).toEqual([REVIEW_PATH]);
    expect((fetchMock.mock.calls[0] as unknown[])[1]).toMatchObject({ headers: { Authorization: 'Bearer test-token' } });
  });

  test("passes apiome-rest's refusal through with its status", async () => {
    mockRest(restStack({ [REVIEW_PATH]: { status: 403, body: { detail: 'Forbidden' } } }));
    const res = await readReview(request(), context());
    expect(res.status).toBe(403);
    expect(await res.json()).toEqual({ success: false, error: 'Forbidden' });
  });

  test('answers 502 for a reply that is not a review', async () => {
    mockRest(restStack({ [REVIEW_PATH]: { status: 200, body: { nope: true } } }));
    const res = await readReview(request(), context());
    expect(res.status).toBe(502);
  });
});

describe('POST /api/reviews/[reviewId]/decision', () => {
  test('forwards the decision and note, and answers the review after it', async () => {
    const after = restReview({ state: 'approved' });
    const decisionPath = `${REVIEW_PATH}/decision`;
    const fetchMock = mockRest(restStack({ [decisionPath]: { status: 200, body: after } }));
    const res = await decide(request('/decision', { decision: 'approve', note: 'Looks good' }), context());
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ success: true, review: after });
    const [, init] = fetchMock.mock.calls[0] as [unknown, RequestInit];
    expect(upstreamPaths(fetchMock)).toEqual([decisionPath]);
    expect(init.method).toBe('POST');
    expect(JSON.parse(String(init.body))).toEqual({ decision: 'approve', note: 'Looks good' });
  });

  test('leaves a blank note out of an approval', async () => {
    const decisionPath = `${REVIEW_PATH}/decision`;
    const fetchMock = mockRest(restStack({ [decisionPath]: { status: 200, body: restReview() } }));
    await decide(request('/decision', { decision: 'approve', note: '  ' }), context());
    const [, init] = fetchMock.mock.calls[0] as [unknown, RequestInit];
    expect(JSON.parse(String(init.body))).toEqual({ decision: 'approve' });
  });

  test('refuses a change request without a note before asking apiome-rest', async () => {
    const fetchMock = mockRest(restStack());
    const res = await decide(request('/decision', { decision: 'request_changes', note: ' ' }), context());
    expect(res.status).toBe(400);
    expect(await res.json()).toEqual({
      success: false,
      error: 'Say what needs to change before requesting changes.',
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  test.each([
    ['not json', 'The request body must be JSON'],
    [{ decision: 'pending' }, 'Choose approve or request changes'],
    [{ decision: 'approve', note: 42 }, 'The note must be text'],
  ])('refuses a malformed body %#', async (body, error) => {
    const fetchMock = mockRest(restStack());
    const res = await decide(request('/decision', body), context());
    expect(res.status).toBe(400);
    expect(((await res.json()) as { error: string }).error).toBe(error);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  test("keeps apiome-rest's status and code, with a reviewer-facing message", async () => {
    mockRest(
      restStack({
        [`${REVIEW_PATH}/decision`]: {
          status: 409,
          body: { detail: { code: 'review-already-decided', message: 'you already decided in this round' } },
        },
      })
    );
    const res = await decide(request('/decision', { decision: 'approve' }), context());
    expect(res.status).toBe(409);
    expect(await res.json()).toEqual({
      success: false,
      error: 'You already decided in this round. Decisions cannot be changed.',
      code: 'review-already-decided',
    });
  });

  test("uses apiome-rest's message for a code the page does not know", async () => {
    mockRest(
      restStack({
        [`${REVIEW_PATH}/decision`]: { status: 403, body: { detail: { code: 'review-new-thing', message: 'Nope' } } },
      })
    );
    const res = await decide(request('/decision', { decision: 'approve' }), context());
    expect(res.status).toBe(403);
    expect(await res.json()).toEqual({ success: false, error: 'Nope', code: 'review-new-thing' });
  });
});

describe('GET /api/reviews/[reviewId]/changes', () => {
  test('classifies the version against the newest published revision', async () => {
    const fetchMock = mockRest(restStack());
    const res = await readChanges(request('/changes'), context());
    const json = (await res.json()) as Record<string, unknown>;
    expect(json).toEqual({
      success: true,
      head: { id: HEAD, label: '2.0.0' },
      baseline: { id: NEW_BASE, label: '1.1.0' },
      initialPublication: false,
      changes: [{ ruleId: 'schema-added', severity: 'non-breaking', pointer: '/components/schemas/Owner' }],
      counts: { breaking: 0, 'non-breaking': 1, 'docs-only': 0, unclassified: 0, total: 1 },
      maxSeverity: 'non-breaking',
      classifiedError: null,
    });
    expect(upstreamPaths(fetchMock)).toEqual([REVIEW_PATH, VERSIONS_PATH, CLASSIFIED_PATH]);
    const [, init] = fetchMock.mock.calls[2] as [unknown, RequestInit];
    expect(JSON.parse(String(init.body))).toEqual({
      base: { project: PROJECT_ID, version: NEW_BASE },
      head: { project: PROJECT_ID, version: HEAD },
    });
  });

  test('says this would be the first publication when nothing is published', async () => {
    const fetchMock = mockRest(restStack({ [VERSIONS_PATH]: { status: 200, body: [REVISIONS[0]] } }));
    const json = (await (await readChanges(request('/changes'), context())).json()) as Record<string, unknown>;
    expect(json).toMatchObject({ success: true, baseline: null, initialPublication: true, changes: [] });
    expect(upstreamPaths(fetchMock)).not.toContain(CLASSIFIED_PATH);
  });

  test('reports a failed classification so the tab can fall back to the plain diff', async () => {
    mockRest(restStack({ [CLASSIFIED_PATH]: { status: 403, body: { detail: 'Missing permission versions:view' } } }));
    const res = await readChanges(request('/changes'), context());
    expect(res.status).toBe(200);
    expect(await res.json()).toMatchObject({
      success: true,
      baseline: { id: NEW_BASE, label: '1.1.0' },
      changes: [],
      classifiedError: 'Missing permission versions:view',
    });
  });

  test("fails with apiome-rest's status when the versions cannot be listed", async () => {
    mockRest(restStack({ [VERSIONS_PATH]: { status: 403, body: { detail: 'Forbidden' } } }));
    const res = await readChanges(request('/changes'), context());
    expect(res.status).toBe(403);
  });
});

describe('GET /api/reviews/[reviewId]/spec', () => {
  test("builds the version under review's document, as the Versions screen does", async () => {
    const fetchMock = mockRest(restStack());
    const res = await readSpec(request('/spec'), context());
    expect(await res.json()).toEqual({
      success: true,
      side: 'head',
      versionId: HEAD,
      versionLabel: '2.0.0',
      spec: '{"openapi":"3.1.0"}',
    });
    expect(upstreamPaths(fetchMock)).toEqual([REVIEW_PATH, VERSIONS_PATH]);
    expect(mockBuildSpec).toHaveBeenCalledWith(
      { id: HEAD, version_id: '2.0.0', shortMessage: 'Adds owners', project_id: PROJECT_ID },
      'Pets API',
      { contact: 'team@acme.io' }
    );
  });

  test("builds the baseline's document for the plain diff", async () => {
    mockRest(restStack());
    const json = (await (await readSpec(request('/spec?side=base'), context())).json()) as Record<string, unknown>;
    expect(json).toMatchObject({ success: true, side: 'base', versionId: NEW_BASE, versionLabel: '1.1.0' });
  });

  test('404s the baseline when nothing is published, without building anything', async () => {
    mockRest(restStack({ [VERSIONS_PATH]: { status: 200, body: [REVISIONS[0]] } }));
    const res = await readSpec(request('/spec?side=base'), context());
    expect(res.status).toBe(404);
    expect(mockBuildSpec).not.toHaveBeenCalled();
  });

  test('never builds a document before the review read succeeds', async () => {
    mockRest(restStack({ [REVIEW_PATH]: { status: 403, body: { detail: 'Forbidden' } } }));
    const res = await readSpec(request('/spec'), context());
    expect(res.status).toBe(403);
    expect(mockBuildSpec).not.toHaveBeenCalled();
  });
});
