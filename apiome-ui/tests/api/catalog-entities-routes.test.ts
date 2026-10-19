/**
 * @jest-environment node
 *
 * The catalog entity proxies — CDG-5.1 (#5979).
 *
 * The tenant comes from the session; the list forwards only `kind`, `team`, `q`, `cursor` and
 * `limit` (well-formed) to `/v1/catalog/{tenant}/entities`, the summary only `team` and `q`; REST's
 * refusal keeps its status.
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
import { GET as listEntities } from '@/app/api/catalog/entities/route';
import { GET as summarize } from '@/app/api/catalog/entities/summary/route';

let upstream: string[] = [];
let reply: { status: number; body: unknown } = { status: 200, body: {} };

beforeEach(() => {
  upstream = [];
  reply = { status: 200, body: { items: [], pagination: { nextCursor: null } } };
  global.fetch = jest.fn(async (input: RequestInfo | URL) => {
    upstream.push(String(input));
    return new Response(JSON.stringify(reply.body), { status: reply.status });
  }) as unknown as typeof fetch;
});

describe('the entity proxies', () => {
  test('the list forwards only the allowed, well-formed parameters', async () => {
    await listEntities(
      new NextRequest('http://ui.test/api/catalog/entities?kind=api&kind=DROP%20TABLE&team=payments&q=orders&cursor=abc&limit=50&evil=1'),
    );
    expect(upstream).toEqual([
      'http://rest.test/v1/catalog/acme/entities?kind=api&team=payments&q=orders&cursor=abc&limit=50',
    ]);
  });

  test('the summary forwards team and q only', async () => {
    await summarize(new NextRequest('http://ui.test/api/catalog/entities/summary?team=payments&kind=api&cursor=x'));
    expect(upstream).toEqual(['http://rest.test/v1/catalog/acme/entities/summary?team=payments']);
  });

  test('REST’s refusal keeps its status', async () => {
    reply = { status: 422, body: { detail: { code: 'kind-invalid', message: 'Unknown entity kind' } } };
    const response = await listEntities(new NextRequest('http://ui.test/api/catalog/entities?kind=galaxy'));
    expect(response.status).toBe(422);
    expect((await response.json()).success).toBe(false);
  });
});
