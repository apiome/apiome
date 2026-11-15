/**
 * @jest-environment node
 */
/**
 * The SDK compatibility proxy — SGD-2.1 (#4735).
 *
 * `GET /api/projects/{projectId}/sdk-compatibility` forwards to apiome-rest with the session's tenant
 * (never the browser's), forwards only `version`, and returns the `{ success, data }` envelope.
 */

import { describe, expect, jest, test, beforeEach } from '@jest/globals';

jest.mock('@lib/primitives-api-proxy', () => ({
  getAuthenticatedTenantContext: jest.fn(),
}));
jest.mock('@lib/rest-auth', () => ({
  REST_API_BASE_URL: 'http://rest.test/v1',
  createRestAuthHeaders: () => ({ Authorization: 'Bearer t' }),
}));

import { NextRequest } from 'next/server';
import { getAuthenticatedTenantContext } from '@lib/primitives-api-proxy';
import { GET } from '@/app/api/projects/[projectId]/sdk-compatibility/route';

const mockContext = getAuthenticatedTenantContext as unknown as jest.Mock;
const fetchMock = jest.fn<typeof fetch>();

function request(query = ''): NextRequest {
  return new NextRequest(`http://ui.test/api/projects/p-1/sdk-compatibility${query}`);
}
const ctx = { params: Promise.resolve({ projectId: 'p-1' }) };

beforeEach(() => {
  fetchMock.mockReset();
  global.fetch = fetchMock as unknown as typeof fetch;
  mockContext.mockReset();
  mockContext.mockResolvedValue({ ok: true, tenantSlug: 'acme corp', user: { user_id: 'u-1' } } as never);
});

describe('SDK compatibility proxy', () => {
  test('forwards to the tenant-scoped REST route with only the version', async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify({ schema_version: 'x' }), { status: 200 }));
    const res = await GET(request('?version=1.0.0&tenant=evil'), ctx);
    expect(await res.json()).toEqual({ success: true, data: { schema_version: 'x' } });
    expect(String(fetchMock.mock.calls[0][0])).toBe(
      'http://rest.test/v1/tenants/acme%20corp/projects/p-1/sdk-compatibility?version=1.0.0',
    );
  });

  test('omits the query for the latest revision', async () => {
    fetchMock.mockResolvedValue(new Response('{}', { status: 200 }));
    await GET(request(), ctx);
    expect(String(fetchMock.mock.calls[0][0])).toBe('http://rest.test/v1/tenants/acme%20corp/projects/p-1/sdk-compatibility');
  });

  test('passes a REST refusal on with its code', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ detail: { code: 'sdk-compat-version-not-found', message: 'no such version' } }), { status: 404 }),
    );
    const res = await GET(request('?version=9.9.9'), ctx);
    expect(res.status).toBe(404);
    expect(await res.json()).toMatchObject({ success: false, code: 'sdk-compat-version-not-found' });
  });

  test('refuses without a session', async () => {
    mockContext.mockResolvedValue({ ok: false, status: 401, error: 'Unauthorized' } as never);
    const res = await GET(request(), ctx);
    expect(res.status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
