/**
 * @jest-environment node
 *
 * The schema registry proxy — CDG-4.5 (#5977).
 *
 * The tenant comes from the session; requests reach `/v1/tenants/{tenant}/schema-registry/…` only
 * for allowed paths and methods; writes carry only their own fields; `GET config` adds the tenant
 * slug and the Confluent URL; REST's refusal keeps its status.
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
import { DELETE, GET, POST, PUT } from '@/app/api/schema-registry/[...path]/route';

let upstream: Array<{ url: string; method: string; body: unknown }> = [];
let reply: { status: number; body: unknown } = { status: 200, body: {} };

beforeEach(() => {
  upstream = [];
  reply = { status: 200, body: { ok: true } };
  global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    upstream.push({
      url: String(input),
      method: init?.method ?? 'GET',
      body: init?.body ? JSON.parse(String(init.body)) : undefined,
    });
    return new Response(JSON.stringify(reply.body), { status: reply.status });
  }) as unknown as typeof fetch;
});

const ctx = (...path: string[]) => ({ params: Promise.resolve({ path }) });
const request = (method: string, body?: unknown) =>
  new NextRequest('http://ui.test/api/schema-registry/x', {
    method,
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });

describe('the schema registry proxy', () => {
  test('GET config adds the tenant slug and the Confluent URL', async () => {
    reply = { status: 200, body: { compatibilityLevel: 'BACKWARD', mode: 'READWRITE' } };
    const response = await GET(request('GET'), ctx('config'));
    expect(upstream[0].url).toBe('http://rest.test/v1/tenants/acme/schema-registry/config');
    expect(await response.json()).toEqual({
      compatibilityLevel: 'BACKWARD',
      mode: 'READWRITE',
      tenantSlug: 'acme',
      registryUrl: 'http://rest.test/registry/schema/acme',
    });
  });

  test('PUT config forwards only the level and mode', async () => {
    await PUT(request('PUT', { compatibilityLevel: 'NONE', mode: 'READONLY', tenant_id: 'other' }), ctx('config'));
    expect(upstream[0]).toEqual({
      url: 'http://rest.test/v1/tenants/acme/schema-registry/config',
      method: 'PUT',
      body: { compatibilityLevel: 'NONE', mode: 'READONLY' },
    });
  });

  test('lists subjects and a subject’s versions', async () => {
    await GET(request('GET'), ctx('subjects'));
    await GET(request('GET'), ctx('subjects', 'orders/v1', 'versions'));
    expect(upstream.map((u) => u.url)).toEqual([
      'http://rest.test/v1/tenants/acme/schema-registry/subjects',
      'http://rest.test/v1/tenants/acme/schema-registry/subjects/orders%2Fv1/versions',
    ]);
  });

  test('attach forwards the item and strategy; detach deletes the subject', async () => {
    await POST(request('POST', { projectId: 'p-1', strategy: 'topic', schema: 'x' }), ctx('subjects', 'orders-value', 'attach'));
    reply = { status: 200, body: [1, 2] };
    const detached = await DELETE(request('DELETE'), ctx('subjects', 'orders-value'));
    expect(upstream[0]).toEqual({
      url: 'http://rest.test/v1/tenants/acme/schema-registry/subjects/orders-value/attach',
      method: 'POST',
      body: { projectId: 'p-1', strategy: 'topic' },
    });
    expect(upstream[1].method).toBe('DELETE');
    expect(await detached.json()).toEqual([1, 2]);
  });

  test('refuses a path it does not forward, without calling REST', async () => {
    const response = await POST(request('POST', { schema: 'x' }), ctx('subjects', 'orders-value', 'versions'));
    expect(response.status).toBe(404);
    expect(upstream).toHaveLength(0);
    expect((await GET(request('GET'), ctx('schemas', 'ids', '1'))).status).toBe(404);
  });

  test('keeps REST’s refusal and message', async () => {
    reply = { status: 403, body: { detail: 'Permission denied: imports:edit' } };
    const response = await PUT(request('PUT', { mode: 'READONLY' }), ctx('config'));
    expect(response.status).toBe(403);
    expect((await response.json()).success).toBe(false);
  });
});
