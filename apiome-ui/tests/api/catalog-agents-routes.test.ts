/**
 * @jest-environment node
 *
 * The agent and model proxies — CDG-5.2 (#5980).
 *
 * The tenant comes from the session; only the allowed paths, methods and fields reach
 * `/v1/tenants/{tenant}/catalog-agents|catalog-models`; a delete stays a 204; REST's refusal keeps
 * its status.
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
import * as agents from '@/app/api/catalog-agents/[[...path]]/route';
import * as models from '@/app/api/catalog-models/[[...path]]/route';

const KEY = '88888888-8888-4888-8888-888888888888';
let upstream: Array<{ url: string; method: string; body: unknown }> = [];
let reply: { status: number; body: unknown } = { status: 200, body: {} };

beforeEach(() => {
  upstream = [];
  reply = { status: 200, body: { ok: true } };
  global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    upstream.push({ url: String(input), method: init?.method ?? 'GET', body: init?.body ? JSON.parse(String(init.body)) : undefined });
    return new Response(reply.status === 204 ? null : JSON.stringify(reply.body), { status: reply.status });
  }) as unknown as typeof fetch;
});

const ctx = (...path: string[]) => ({ params: Promise.resolve({ path: path.length ? path : undefined }) });
const request = (method: string, body?: unknown) =>
  new NextRequest('http://ui.test/api/x', { method, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });

describe('the agent and model proxies', () => {
  test('lists and registers, forwarding only the allowed fields', async () => {
    await agents.GET(request('GET'), ctx());
    await agents.POST(request('POST', { name: 'Bot', keyIds: [KEY], tenantId: 'other' }), ctx());
    await models.POST(request('POST', { provider: 'Meta', modelName: 'llama', secret: 'x' }), ctx());
    expect(upstream).toEqual([
      { url: 'http://rest.test/v1/tenants/acme/catalog-agents', method: 'GET', body: undefined },
      { url: 'http://rest.test/v1/tenants/acme/catalog-agents', method: 'POST', body: { name: 'Bot', keyIds: [KEY] } },
      { url: 'http://rest.test/v1/tenants/acme/catalog-models', method: 'POST', body: { provider: 'Meta', modelName: 'llama' } },
    ]);
  });

  test('links a key and deletes an agent (a 204)', async () => {
    await agents.PUT(request('PUT'), ctx('support-bot', 'keys', KEY));
    reply = { status: 204, body: {} };
    const deleted = await agents.DELETE(request('DELETE'), ctx('support-bot'));
    expect(upstream.map((u) => `${u.method} ${u.url}`)).toEqual([
      `PUT http://rest.test/v1/tenants/acme/catalog-agents/support-bot/keys/${KEY}`,
      'DELETE http://rest.test/v1/tenants/acme/catalog-agents/support-bot',
    ]);
    expect(deleted.status).toBe(204);
  });

  test('refuses what it does not forward, without calling REST', async () => {
    expect((await agents.DELETE(request('DELETE'), ctx())).status).toBe(404);
    expect((await models.PUT(request('PUT'), ctx('claude', 'keys', KEY))).status).toBe(404);
    expect((await agents.GET(request('GET'), ctx('Bad Slug'))).status).toBe(404);
    expect(upstream).toHaveLength(0);
  });

  test('keeps REST’s refusal', async () => {
    reply = { status: 409, body: { detail: { code: 'agent-key-taken', message: 'that agent key already belongs to another agent' } } };
    const response = await agents.PUT(request('PUT'), ctx('support-bot', 'keys', KEY));
    expect(response.status).toBe(409);
    expect((await response.json()).error).toContain('another agent');
  });
});
