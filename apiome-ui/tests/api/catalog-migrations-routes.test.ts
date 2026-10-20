/**
 * @jest-environment node
 *
 * The catalog imports proxy — CDG-5.5 (#5983): the report list and reads, the Compass upload, the
 * accept/dismiss decisions and the component read map onto their apiome-rest routes with only
 * their own fields; anything else is a 404 without calling apiome-rest.
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
import { GET, POST } from '@/app/api/catalog-migrations/[[...path]]/route';

const RUN = '11111111-1111-4111-8111-111111111111';
const SUGGESTION = '22222222-2222-4222-8222-222222222222';
let upstream: Array<{ url: string; method: string; body: unknown }> = [];

beforeEach(() => {
  upstream = [];
  global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    upstream.push({ url: String(input), method: String(init?.method), body: init?.body ? JSON.parse(String(init.body)) : undefined });
    return new Response(JSON.stringify({ runs: [] }), { status: 200 });
  }) as unknown as typeof fetch;
});

const ctx = (...path: string[]) => ({ params: Promise.resolve({ path: path.length ? path : undefined }) });
const post = (body: unknown) =>
  new NextRequest('http://ui.test/api/catalog-migrations', { method: 'POST', body: JSON.stringify(body) });

describe('the catalog imports proxy', () => {
  test('reads the list, a report and a component', async () => {
    await GET(new NextRequest('http://ui.test/api/catalog-migrations'), ctx());
    await GET(new NextRequest('http://ui.test/x'), ctx(RUN));
    await GET(new NextRequest('http://ui.test/x'), ctx('components', 'payments-svc'));
    expect(upstream.map((call) => call.url)).toEqual([
      'http://rest.test/v1/tenants/acme/catalog-migrations',
      `http://rest.test/v1/tenants/acme/catalog-migrations/${RUN}`,
      'http://rest.test/v1/tenants/acme/catalog-components/payments-svc',
    ]);
  });

  test('uploads and decides with only their own fields', async () => {
    await POST(post({ filename: 'c.json', content: '{}', tenant: 'other' }), ctx('compass'));
    await POST(post({ slug: 'payments', role: 'admin' }), ctx('suggestions', SUGGESTION, 'accept'));
    await POST(post({ anything: true }), ctx('suggestions', SUGGESTION, 'dismiss'));
    expect(upstream).toEqual([
      { url: 'http://rest.test/v1/tenants/acme/catalog-migrations/compass', method: 'POST', body: { filename: 'c.json', content: '{}' } },
      {
        url: `http://rest.test/v1/tenants/acme/catalog-migration-suggestions/${SUGGESTION}/accept`,
        method: 'POST',
        body: { slug: 'payments' },
      },
      { url: `http://rest.test/v1/tenants/acme/catalog-migration-suggestions/${SUGGESTION}/dismiss`, method: 'POST', body: {} },
    ]);
  });

  test('refuses every other path without calling apiome-rest', async () => {
    expect((await GET(new NextRequest('http://ui.test/x'), ctx('compass'))).status).toBe(404);
    expect((await POST(post({}), ctx())).status).toBe(404);
    expect((await POST(post({}), ctx('suggestions', 'nope', 'accept'))).status).toBe(404);
    expect((await GET(new NextRequest('http://ui.test/x'), ctx('components', 'a', 'b'))).status).toBe(404);
    expect(upstream).toHaveLength(0);
  });
});
