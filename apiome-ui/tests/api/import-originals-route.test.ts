/**
 * @jest-environment node
 *
 * The import original proxy (COA-5.3, #7079): the tenant comes from the session, the body is
 * forwarded to `POST /v1/tenants/{tenant}/import-originals`, a non-object body is refused before REST, and
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
import { POST } from '@/app/api/import-originals/route';

let upstream: { url: string; method?: string; body?: string }[] = [];
let reply: { status: number; body: unknown } = { status: 201, body: {} };

beforeEach(() => {
  upstream = [];
  reply = { status: 200, body: { stored: true } };
  global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    upstream.push({ url: String(input), method: init?.method, body: init?.body as string | undefined });
    return new Response(JSON.stringify(reply.body), { status: reply.status });
  }) as unknown as typeof fetch;
});

function post(body: string): NextRequest {
  return new NextRequest('http://ui.test/api/import-originals', { method: 'POST', body });
}

describe('POST /api/import-originals', () => {
  test('forwards the record to the tenant’s import-originals', async () => {
    const record = { versionId: 'v-1', content: 'openapi: 3.1.0\n', filename: 'pets.yaml' };
    const response = await POST(post(JSON.stringify(record)));
    expect(response.ok).toBe(true);
    expect(upstream).toHaveLength(1);
    expect(upstream[0].url).toBe('http://rest.test/v1/tenants/acme/import-originals');
    expect(upstream[0].method).toBe('POST');
    expect(JSON.parse(upstream[0].body!)).toEqual(record);
  });

  test('a body that is not an object never reaches REST', async () => {
    expect((await POST(post('[1]'))).status).toBe(400);
    expect((await POST(post('not json'))).status).toBe(400);
    expect(upstream).toEqual([]);
  });

  test('REST’s refusal keeps its status', async () => {
    reply = { status: 403, body: { detail: 'Only the user who created the version can record its original.' } };
    const response = await POST(post(JSON.stringify({ versionId: 'v-1', content: 'a: 1' })));
    expect(response.status).toBe(403);
    expect((await response.json()).success).toBe(false);
  });
});
