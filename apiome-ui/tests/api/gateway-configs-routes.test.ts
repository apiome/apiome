/**
 * @jest-environment node
 *
 * The gateway configs proxy — CDG-5.3 (#5981): read-only, the list (with a well-formed `connector`)
 * and one read by slug; anything else is a 404 without calling apiome-rest.
 */

import { beforeEach, describe, expect, jest, test } from '@jest/globals';

jest.mock('@lib/primitives-api-proxy', () => ({
  getAuthenticatedTenantContext: jest.fn(async () => ({
    ok: true,
    user: { user_id: 'u-1', email: 'ada@acme.io' },
    tenantSlug: 'acme',
  })),
}));

jest.mock('@lib/rest-auth', () => ({
  createRestAuthHeaders: jest.fn(() => ({ Authorization: 'Bearer test-token' })),
  REST_API_BASE_URL: 'http://rest.test/v1',
}));

import { NextRequest } from 'next/server';
import { GET } from '@/app/api/gateway-configs/[[...path]]/route';

const CONNECTOR = '44444444-4444-4444-8444-444444444444';
let upstream: string[] = [];

beforeEach(() => {
  upstream = [];
  global.fetch = jest.fn(async (input: RequestInfo | URL) => {
    upstream.push(String(input));
    return new Response(JSON.stringify({ gatewayConfigs: [] }), { status: 200 });
  }) as unknown as typeof fetch;
});

const ctx = (...path: string[]) => ({ params: Promise.resolve({ path: path.length ? path : undefined }) });

describe('the gateway configs proxy', () => {
  test('lists, passing only a well-formed connector id', async () => {
    await GET(new NextRequest(`http://ui.test/api/gateway-configs?connector=${CONNECTOR}&evil=1`), ctx());
    await GET(new NextRequest('http://ui.test/api/gateway-configs?connector=nope'), ctx());
    expect(upstream).toEqual([
      `http://rest.test/v1/tenants/acme/gateway-configs?connector=${CONNECTOR}`,
      'http://rest.test/v1/tenants/acme/gateway-configs',
    ]);
  });

  test('reads one by slug and refuses anything else', async () => {
    await GET(new NextRequest('http://ui.test/api/gateway-configs/kong-konnect-prod'), ctx('kong-konnect-prod'));
    expect(upstream).toEqual(['http://rest.test/v1/tenants/acme/gateway-configs/kong-konnect-prod']);
    expect((await GET(new NextRequest('http://ui.test/x'), ctx('a', 'b'))).status).toBe(404);
    expect((await GET(new NextRequest('http://ui.test/x'), ctx('Bad Slug'))).status).toBe(404);
    expect(upstream).toHaveLength(1);
  });
});
