/**
 * @jest-environment node
 *
 * The entity facts proxy — CDG-5.4 (#5982): forwards to `/v1/catalog/{tenant}/entities/{kind}/{id}/facts`
 * for a well-formed kind and id, refuses anything else without calling apiome-rest, keeps REST's status.
 */

import { beforeEach, describe, expect, jest, test } from '@jest/globals';

jest.mock('@lib/primitives-api-proxy', () => ({
  getAuthenticatedTenantContext: jest.fn(async () => ({ ok: true, user: { user_id: 'u-1' }, tenantSlug: 'acme' })),
}));

jest.mock('@lib/rest-auth', () => ({
  createRestAuthHeaders: jest.fn(() => ({ Authorization: 'Bearer test-token' })),
  REST_API_BASE_URL: 'http://rest.test/v1',
}));

import { NextRequest } from 'next/server';
import { GET } from '@/app/api/catalog/entities/[kind]/[id]/facts/route';

const ID = '22222222-2222-4222-8222-222222222222';
let upstream: string[] = [];
let status = 200;

beforeEach(() => {
  upstream = [];
  status = 200;
  global.fetch = jest.fn(async (input: RequestInfo | URL) => {
    upstream.push(String(input));
    return new Response(JSON.stringify({ facts: [], score: null }), { status });
  }) as unknown as typeof fetch;
});

const ctx = (kind: string, id: string) => ({ params: Promise.resolve({ kind, id }) });

describe('the facts proxy', () => {
  test('forwards a well-formed request', async () => {
    await GET(new NextRequest('http://ui.test/x'), ctx('spec', ID));
    expect(upstream).toEqual([`http://rest.test/v1/catalog/acme/entities/spec/${ID}/facts`]);
  });

  test('refuses a malformed kind or id', async () => {
    expect((await GET(new NextRequest('http://ui.test/x'), ctx('../x', ID))).status).toBe(404);
    expect((await GET(new NextRequest('http://ui.test/x'), ctx('spec', 'nope'))).status).toBe(404);
    expect(upstream).toHaveLength(0);
  });

  test('keeps REST’s refusal', async () => {
    status = 403;
    expect((await GET(new NextRequest('http://ui.test/x'), ctx('connector', ID))).status).toBe(403);
  });
});
