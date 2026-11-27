/**
 * @jest-environment node
 */
/**
 * `/api/pact/publish/compare` — PFX-8.4 (#7301): the proxy forwards exactly `{ pact, against }` to
 * `POST /v1/tenants/{slug}/pact-broker/pacts/check` as the signed-in user, and refuses anything
 * else with a 400 naming it, without calling REST.
 */

import { jest } from '@jest/globals';
import { NextResponse } from 'next/server';

const forwarded: Array<{ url: string; method: string; body?: unknown }> = [];

jest.mock('@lib/connectors-proxy', () => ({
  resolveConnectorTenant: async () => ({ user: { user_id: 'u-1' }, slug: 'acme' }),
  tenantUrl: (slug: string, path: string) => `http://rest/v1/tenants/${slug}/${path}`,
  forwardConnectorRequest: async (url: string, init: { method: string; body?: unknown }) => {
    forwarded.push({ url, method: init.method, body: init.body });
    return NextResponse.json({ ok: true });
  },
}));
jest.mock('@lib/rest-auth', () => ({
  createRestAuthHeaders: () => ({ Authorization: 'Bearer session' }),
  REST_API_BASE_URL: 'http://rest/v1',
}));

import { POST } from '../src/app/api/pact/publish/compare/route';

const PACT = { consumer: { name: 'Orders UI' }, provider: { name: 'Billing Service' }, interactions: [] };

function post(body: unknown) {
  return POST(new Request('http://x', { method: 'POST', body: typeof body === 'string' ? body : JSON.stringify(body) }) as never);
}

beforeEach(() => {
  forwarded.length = 0;
});

describe('/api/pact/publish/compare', () => {
  it('forwards the pact and its selectors to the check route', async () => {
    const response = await post({ pact: PACT, against: ['main', 'deployed:production'] });
    expect(response.status).toBe(200);
    expect(forwarded).toEqual([
      {
        url: 'http://rest/v1/tenants/acme/pact-broker/pacts/check',
        method: 'POST',
        body: { pact: PACT, against: ['main', 'deployed:production'] },
      },
    ]);
  });

  it.each([
    ['not JSON', 'nope'],
    ['an unknown field', { pact: PACT, against: ['main'], publish: true }],
    ['no pact', { against: ['main'] }],
    ['no selectors', { pact: PACT, against: [] }],
  ])('refuses %s without calling REST', async (_what, body) => {
    const response = await post(body);
    expect(response.status).toBe(400);
    expect(((await response.json()) as { success: boolean }).success).toBe(false);
    expect(forwarded).toEqual([]);
  });
});
