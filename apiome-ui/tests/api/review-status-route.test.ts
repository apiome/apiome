/**
 * @jest-environment node
 *
 * `GET /api/reviews/status` — the review status surfaces' one read (COL-2.4, #4520).
 *
 * Runs under the node environment: `next/server` needs the WHATWG `Request`/`Response` globals.
 *
 * The route is a direct database read rather than an apiome-rest proxy, so what it refuses matters
 * as much as what it returns. Pinned here:
 *
 *   1. **The tenant comes from the session**, never from the query string — a caller cannot ask
 *      about another workspace.
 *   2. **A signed-out or tenant-less caller is refused** before the database is touched.
 *   3. **A project id that is not a UUID is a 400**, not a 500 — `::uuid` would abort the
 *      statement, and a typo in a query string must not read as a server fault.
 *   4. The reply is `{success, reviews}`, and a thrown read is a 500 with no rows.
 */

import { describe, test, expect, jest, beforeEach } from '@jest/globals';

jest.mock('@lib/auth/server-session', () => ({
  getAuthSession: jest.fn(),
}));

jest.mock('@lib/db/review-status', () => ({
  listOpenReviews: jest.fn(),
}));

import { NextRequest } from 'next/server';
import { getAuthSession } from '@lib/auth/server-session';
import { listOpenReviews } from '@lib/db/review-status';
import { GET } from '@/app/api/reviews/status/route';

const mockSession = getAuthSession as unknown as jest.Mock;
const mockList = listOpenReviews as unknown as jest.Mock;

const TENANT = '550e8400-e29b-41d4-a716-446655440000';
const PROJECT = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const USER = { user_id: '660e8400-e29b-41d4-a716-446655440001', current_tenant_id: TENANT };

const ROW = {
  reviewId: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
  projectId: PROJECT,
  versionId: 'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
  versionLabel: '1.2.0',
  state: 'in_review',
  round: 1,
  reviewerCount: 2,
  approvedCount: 1,
  changesRequestedCount: 0,
  pendingCount: 1,
  updatedAt: '2026-09-01T10:00:00.000Z',
};

/** Call the handler with a query string. */
function call(query = ''): Promise<Response> {
  return GET(new NextRequest(`http://localhost/api/reviews/status${query}`)) as unknown as Promise<Response>;
}

beforeEach(() => {
  jest.clearAllMocks();
  mockSession.mockResolvedValue({ user: USER } as never);
  mockList.mockResolvedValue([ROW] as never);
});

describe('GET /api/reviews/status', () => {
  test('reads the whole tenant when no project is named', async () => {
    const response = await call();
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ success: true, reviews: [ROW] });
    expect(mockList).toHaveBeenCalledWith(TENANT, null);
  });

  test('narrows to one project when asked', async () => {
    await call(`?projectId=${PROJECT}`);
    expect(mockList).toHaveBeenCalledWith(TENANT, PROJECT);
  });

  test('takes the tenant from the session, not from the caller', async () => {
    await call('?tenantId=99999999-9999-4999-8999-999999999999');
    expect(mockList).toHaveBeenCalledWith(TENANT, null);
  });

  test('refuses a signed-out caller before reading anything', async () => {
    mockSession.mockResolvedValue(null as never);
    const response = await call();
    expect(response.status).toBe(401);
    expect(mockList).not.toHaveBeenCalled();
  });

  test('refuses a caller with no tenant selected', async () => {
    mockSession.mockResolvedValue({ user: { user_id: USER.user_id } } as never);
    const response = await call();
    expect(response.status).toBe(400);
    expect(mockList).not.toHaveBeenCalled();
  });

  test('refuses a project id that is not a UUID rather than letting ::uuid abort', async () => {
    const response = await call('?projectId=not-a-uuid');
    expect(response.status).toBe(400);
    expect((await response.json()).error).toMatch(/UUID/i);
    expect(mockList).not.toHaveBeenCalled();
  });

  test('treats a blank project id as no filter', async () => {
    await call('?projectId=%20%20');
    expect(mockList).toHaveBeenCalledWith(TENANT, null);
  });

  test('answers 500 with no rows when the read throws', async () => {
    mockList.mockRejectedValue(new Error('connection reset') as never);
    const response = await call();
    expect(response.status).toBe(500);
    expect(await response.json()).toEqual({ success: false, error: 'connection reset' });
  });
});
