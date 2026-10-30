/**
 * @jest-environment node
 *
 * The URL import record proxy (RAR-6.1, #3538): the tenant comes from the session, the body is
 * forwarded to `POST /v1/tenants/{tenant}/url-imports`, a non-object body is refused before REST, and
 * REST's refusal keeps its status.
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
import { POST } from '@/app/api/url-imports/route';

let upstream: { url: string; method?: string; body?: string }[] = [];
let reply: { status: number; body: unknown } = { status: 201, body: {} };

beforeEach(() => {
  upstream = [];
  reply = { status: 201, body: { id: 's-1' } };
  global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    upstream.push({ url: String(input), method: init?.method, body: init?.body as string | undefined });
    return new Response(JSON.stringify(reply.body), { status: reply.status });
  }) as unknown as typeof fetch;
});

function post(body: string): NextRequest {
  return new NextRequest('http://ui.test/api/url-imports', { method: 'POST', body });
}

describe('POST /api/url-imports', () => {
  test('forwards the record to the tenant’s url-imports', async () => {
    const record = { projectId: 'p-1', url: 'https://specs.example.com/orders.json', options: {} };
    const response = await POST(post(JSON.stringify(record)));
    expect(response.ok).toBe(true);
    expect(upstream).toHaveLength(1);
    expect(upstream[0].url).toBe('http://rest.test/v1/tenants/acme/url-imports');
    expect(upstream[0].method).toBe('POST');
    expect(JSON.parse(upstream[0].body!)).toEqual(record);
  });

  test('a body that is not an object never reaches REST', async () => {
    expect((await POST(post('[1]'))).status).toBe(400);
    expect((await POST(post('not json'))).status).toBe(400);
    expect(upstream).toEqual([]);
  });

  test('REST’s refusal keeps its status', async () => {
    reply = { status: 422, body: { detail: 'Only http and https URLs can be refreshed.' } };
    const response = await POST(post(JSON.stringify({ projectId: 'p-1', url: 'ftp://x' })));
    expect(response.status).toBe(422);
    expect((await response.json()).success).toBe(false);
  });
});
