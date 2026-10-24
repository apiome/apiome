/**
 * @jest-environment node
 *
 * The two-factor policy BFF route — TFA-1.3 (#5657).
 *
 * Drives the real handlers with the tenant context and the upstream `fetch` mocked: the tenant comes
 * from the session, `PUT` forwards only well-formed policy fields, and REST's refusal keeps its
 * status (a member without `members:edit` sees REST's 403).
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
import { GET, PUT } from '@/app/api/two-factor-policy/route';

let upstream: Array<{ url: string; method: string; body: unknown }> = [];
let reply: { status: number; body: unknown } = { status: 200, body: {} };

beforeEach(() => {
  upstream = [];
  reply = { status: 200, body: { require_two_factor: false, grace_days: 7 } };
  global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    upstream.push({
      url: String(input),
      method: init?.method ?? 'GET',
      body: init?.body ? JSON.parse(String(init.body)) : undefined,
    });
    return new Response(JSON.stringify(reply.body), { status: reply.status });
  }) as unknown as typeof fetch;
});

/** A PUT carrying `body` as JSON. */
const put = (body: unknown) =>
  new NextRequest('http://ui.test/api/two-factor-policy', { method: 'PUT', body: JSON.stringify(body) });

describe('/api/two-factor-policy', () => {
  test('GET reads the session tenant’s policy', async () => {
    const response = await GET();
    expect(response.status).toBe(200);
    expect(upstream).toEqual([
      { url: 'http://rest.test/v1/tenants/acme/two-factor-policy', method: 'GET', body: undefined },
    ]);
  });

  test('PUT forwards the switch and a valid grace period', async () => {
    await PUT(put({ require_two_factor: true, grace_days: 14 }));
    expect(upstream[0]).toEqual({
      url: 'http://rest.test/v1/tenants/acme/two-factor-policy',
      method: 'PUT',
      body: { require_two_factor: true, grace_days: 14 },
    });
  });

  test('PUT drops anything else, including an out-of-range grace period', async () => {
    await PUT(put({ require_two_factor: 'yes', grace_days: 365, tenant_id: 'someone-else' }));
    expect(upstream[0].body).toEqual({});
  });

  test('a REST refusal keeps its status', async () => {
    reply = { status: 403, body: { detail: 'Permission denied: members:edit' } };
    const response = await PUT(put({ require_two_factor: true }));
    expect(response.status).toBe(403);
  });
});
