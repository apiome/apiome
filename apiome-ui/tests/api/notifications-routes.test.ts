/**
 * @jest-environment node
 *
 * The notification BFF routes (COL-3.2, #4522).
 *
 * Runs under the node environment: `next/server` needs the WHATWG `Request`/`Response`
 * globals.
 *
 * Drives the real handlers with the session, the tenant lookup and the upstream `fetch`
 * mocked, and pins the four things this layer exists for:
 *
 * 1. **The tenant comes from the session**, never from the browser — a caller cannot read
 *    another workspace's inbox by naming its slug.
 * 2. **Only the whitelist reaches apiome-rest.** A hand-made query with `user_id` on it is
 *    forwarded without that parameter, not refused with an explanation of how to try again.
 * 3. **A refusal keeps its status and its message**, so the page says what apiome-rest said
 *    rather than "something went wrong".
 * 4. **A mark-read body that names nothing markable is refused here**, before a request is
 *    made at all.
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
import { GET as listNotifications } from '@/app/api/notifications/route';
import { GET as unreadCount } from '@/app/api/notifications/unread-count/route';
import { POST as markRead } from '@/app/api/notifications/read/route';
import { restErrorMessage } from '@/app/api/notifications/notifications-proxy';

const mockSession = getAuthSession as unknown as jest.Mock;
const mockTenant = getTenantById as unknown as jest.Mock;

const TENANT_ID = '550e8400-e29b-41d4-a716-446655440000';
const NOTIFICATION_ID = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
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

/** The request options the handler passed. */
function calledInit(): RequestInit {
  return (fetchMock.mock.calls[0] as unknown[])[1] as RequestInit;
}

/**
 * A GET request to the list route.
 *
 * @param query - The query string, without its leading `?`.
 * @returns The request.
 */
function listRequest(query = ''): NextRequest {
  return new NextRequest(`http://ui.test/api/notifications${query ? `?${query}` : ''}`);
}

/**
 * A POST request to the mark-read route.
 *
 * @param body - The body to send, already an object (or a raw string for bad JSON).
 * @returns The request.
 */
function readRequest(body: unknown): NextRequest {
  return new NextRequest('http://ui.test/api/notifications/read', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: typeof body === 'string' ? body : JSON.stringify(body),
  });
}

beforeEach(() => {
  jest.clearAllMocks();
  mockSession.mockResolvedValue({ user: USER });
  mockTenant.mockResolvedValue({ id: TENANT_ID, slug: 'acme' });
  upstream({ notifications: [], count: 0, total: 0, limit: 50, offset: 0 });
});

describe('who is allowed to ask', () => {
  test('refuses a request with no session', async () => {
    mockSession.mockResolvedValue(null);
    const response = await listNotifications(listRequest());
    expect(response.status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  test('refuses a session with no workspace selected', async () => {
    mockSession.mockResolvedValue({ user: { ...USER, current_tenant_id: undefined } });
    const response = await listNotifications(listRequest());
    expect(response.status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  test('answers 404 when the session names a workspace that is gone', async () => {
    mockTenant.mockResolvedValue(null);
    const response = await unreadCount();
    expect(response.status).toBe(404);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  test('addresses apiome-rest with the session’s own tenant slug', async () => {
    await listNotifications(listRequest());
    expect(mockTenant).toHaveBeenCalledWith(TENANT_ID);
    expect(calledUrl()).toContain('http://rest.test/v1/tenants/acme/notifications');
  });

  test('ignores a tenant the caller tries to name in the query', async () => {
    await listNotifications(listRequest('tenant=someone-else&tenantSlug=someone-else'));
    expect(calledUrl()).toContain('/tenants/acme/notifications');
    expect(calledUrl()).not.toContain('someone-else');
  });
});

describe('GET /api/notifications', () => {
  test('forwards the whitelist and nothing else', async () => {
    await listNotifications(listRequest('unread=true&type=mention&limit=10&offset=5&user_id=x'));
    const url = new URL(calledUrl());
    expect(Object.fromEntries(url.searchParams)).toEqual({
      unread: 'true',
      type: 'mention',
      limit: '10',
      offset: '5',
    });
  });

  test('never caches: an unread list must not be answered from a stale copy', async () => {
    await listNotifications(listRequest());
    expect(calledInit().cache).toBe('no-store');
  });

  test('passes the page through under a success envelope', async () => {
    upstream({
      notifications: [{ id: NOTIFICATION_ID, type: 'mention' }],
      count: 1,
      total: 3,
      limit: 50,
      offset: 0,
    });
    const response = await listNotifications(listRequest());
    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toMatchObject({
      success: true,
      total: 3,
      notifications: [{ id: NOTIFICATION_ID }],
    });
  });

  test('keeps apiome-rest’s status and message when it refuses', async () => {
    upstream({ detail: { code: 'notification-forbidden', message: 'No inbox for this token' } }, 403);
    const response = await listNotifications(listRequest());
    expect(response.status).toBe(403);
    await expect(response.json()).resolves.toEqual({
      success: false,
      error: 'No inbox for this token',
    });
  });

  test('answers 502 for a reply that is not JSON at all', async () => {
    upstream('<html>gateway</html>', 200);
    const response = await listNotifications(listRequest());
    expect(response.status).toBe(502);
  });
});

describe('GET /api/notifications/unread-count', () => {
  test('passes the tallies through', async () => {
    upstream({ total: 3, by_type: { mention: 2, review_requested: 1 } });
    const response = await unreadCount();
    expect(calledUrl()).toBe('http://rest.test/v1/tenants/acme/notifications/unread-count');
    await expect(response.json()).resolves.toEqual({
      success: true,
      unread: { total: 3, by_type: { mention: 2, review_requested: 1 } },
    });
  });
});

describe('POST /api/notifications/read', () => {
  test('forwards a list of ids', async () => {
    upstream({ marked: 1, unread: { total: 0, by_type: {} } });
    const response = await markRead(readRequest({ ids: [NOTIFICATION_ID] }));
    expect(calledUrl()).toBe('http://rest.test/v1/tenants/acme/notifications/read');
    expect(calledInit().method).toBe('POST');
    expect(JSON.parse(String(calledInit().body))).toEqual({ ids: [NOTIFICATION_ID] });
    await expect(response.json()).resolves.toMatchObject({ success: true, marked: 1 });
  });

  test('forwards `all`', async () => {
    upstream({ marked: 7, unread: { total: 0, by_type: {} } });
    await markRead(readRequest({ all: true }));
    expect(JSON.parse(String(calledInit().body))).toEqual({ all: true });
  });

  test('drops ids that are not UUIDs before they reach a ::uuid cast', async () => {
    upstream({ marked: 1, unread: { total: 0, by_type: {} } });
    await markRead(readRequest({ ids: ['nope', NOTIFICATION_ID] }));
    expect(JSON.parse(String(calledInit().body))).toEqual({ ids: [NOTIFICATION_ID] });
  });

  test('refuses a body that names nothing markable, without calling apiome-rest', async () => {
    for (const body of [{}, { ids: [] }, { all: 'yes' }, 'not json at all']) {
      const response = await markRead(readRequest(body));
      expect(response.status).toBe(400);
    }
    expect(fetchMock).not.toHaveBeenCalled();
  });

  test('keeps apiome-rest’s refusal', async () => {
    upstream({ detail: 'Nope' }, 409);
    const response = await markRead(readRequest({ all: true }));
    expect(response.status).toBe(409);
    await expect(response.json()).resolves.toEqual({ success: false, error: 'Nope' });
  });
});

describe('restErrorMessage', () => {
  test('reads the three shapes apiome-rest answers with', () => {
    expect(restErrorMessage({ detail: { code: 'x', message: 'Told you' } }, 'fallback')).toBe(
      'Told you'
    );
    expect(restErrorMessage({ detail: 'Plain' }, 'fallback')).toBe('Plain');
    expect(restErrorMessage({ detail: [{ loc: ['body'] }] }, 'fallback')).toBe(
      'The request was not valid'
    );
  });

  test('falls back rather than printing an object', () => {
    expect(restErrorMessage(null, 'fallback')).toBe('fallback');
    expect(restErrorMessage({ detail: {} }, 'fallback')).toBe('fallback');
    expect(restErrorMessage({ error: 'From the envelope' }, 'fallback')).toBe(
      'From the envelope'
    );
  });
});
