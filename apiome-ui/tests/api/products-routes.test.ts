/**
 * @jest-environment node
 *
 * The API products proxy — APX-1.1 (#6098): the list, one product and its members map onto
 * apiome-rest's `/v1/tenants/{t}/products…` routes with only their own fields; anything else is a
 * 404 without calling apiome-rest.
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
import { DELETE, GET, PATCH, POST } from '@/app/api/products/[[...path]]/route';

const MEMBER = '11111111-1111-4111-8111-111111111111';
let upstream: Array<{ url: string; method: string; body: unknown }> = [];

beforeEach(() => {
  upstream = [];
  global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    upstream.push({ url: String(input), method: String(init?.method), body: init?.body ? JSON.parse(String(init.body)) : undefined });
    return new Response(JSON.stringify({ products: [] }), { status: 200 });
  }) as unknown as typeof fetch;
});

const ctx = (...path: string[]) => ({ params: Promise.resolve({ path: path.length ? path : undefined }) });
const withBody = (method: string, body: unknown) =>
  new NextRequest('http://ui.test/api/products', { method, body: JSON.stringify(body) });
const bare = () => new NextRequest('http://ui.test/api/products');

describe('the API products proxy', () => {
  test('reads the list, a product and its members', async () => {
    await GET(bare(), ctx());
    await GET(bare(), ctx('payments'));
    await GET(bare(), ctx('payments', 'members'));
    expect(upstream.map((call) => `${call.method} ${call.url}`)).toEqual([
      'GET http://rest.test/v1/tenants/acme/products',
      'GET http://rest.test/v1/tenants/acme/products/payments',
      'GET http://rest.test/v1/tenants/acme/products/payments/members',
    ]);
  });

  test('writes with only their own fields', async () => {
    await POST(withBody('POST', { name: 'Payments', slug: 'payments', tenant: 'other', members: [] }), ctx());
    await PATCH(withBody('PATCH', { visibility: 'portal', slug: 'renamed', owner_team: null }), ctx('payments'));
    await POST(withBody('POST', { kind: 'project_version', ref: 'refunds', version: '2.x', name: 'x' }), ctx('payments', 'members'));
    await DELETE(bare(), ctx('payments', 'members', MEMBER));
    await DELETE(bare(), ctx('payments'));
    expect(upstream).toEqual([
      { url: 'http://rest.test/v1/tenants/acme/products', method: 'POST', body: { name: 'Payments', slug: 'payments' } },
      { url: 'http://rest.test/v1/tenants/acme/products/payments', method: 'PATCH', body: { visibility: 'portal', owner_team: null } },
      {
        url: 'http://rest.test/v1/tenants/acme/products/payments/members',
        method: 'POST',
        body: { kind: 'project_version', ref: 'refunds', version: '2.x' },
      },
      { url: `http://rest.test/v1/tenants/acme/products/payments/members/${MEMBER}`, method: 'DELETE', body: undefined },
      { url: 'http://rest.test/v1/tenants/acme/products/payments', method: 'DELETE', body: undefined },
    ]);
  });

  test('refuses every other path or method without calling apiome-rest', async () => {
    expect((await DELETE(bare(), ctx())).status).toBe(404);
    expect((await POST(withBody('POST', {}), ctx('payments'))).status).toBe(404);
    expect((await GET(bare(), ctx('Not A Slug'))).status).toBe(404);
    expect((await GET(bare(), ctx('payments', 'plans'))).status).toBe(404);
    expect((await DELETE(bare(), ctx('payments', 'members', 'not-a-uuid'))).status).toBe(404);
    expect((await GET(bare(), ctx('payments', 'members', MEMBER))).status).toBe(404);
    expect((await GET(bare(), ctx('payments', 'members', MEMBER, 'x'))).status).toBe(404);
    expect(upstream).toHaveLength(0);
  });
});
