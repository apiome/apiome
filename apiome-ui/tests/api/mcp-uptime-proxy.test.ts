/**
 * @jest-environment node
 *
 * The MCP endpoint uptime proxy — V2-MCP-27.3 / MCAT-13.3 (#3713).
 *
 * The tenant comes from the session; the endpoint id must be a UUID; only `window_hours` and `limit`
 * are forwarded, and only as integers; the upstream status (e.g. a cross-tenant 404) is kept.
 */

import { beforeEach, describe, expect, jest, test } from '@jest/globals';

const proxyRestGet = jest.fn<
  (user: unknown, path: string) => Promise<{ data: unknown; error: string | null; status: number }>
>();

jest.mock('@lib/primitives-api-proxy', () => ({
  getAuthenticatedTenantContext: jest.fn(async () => ({
    ok: true,
    user: { user_id: 'u-1' },
    tenantSlug: 'acme',
  })),
  proxyRestGet: (user: unknown, path: string) => proxyRestGet(user, path),
}));

import { GET } from '@/app/api/mcp/endpoints/[endpointId]/uptime/route';

const EP = '11111111-1111-4111-8111-111111111111';
const ctx = (endpointId: string) => ({ params: Promise.resolve({ endpointId }) });
const request = (query = '') => new Request(`http://ui.test/api/mcp/endpoints/${EP}/uptime${query}`);

beforeEach(() => {
  proxyRestGet.mockReset();
  proxyRestGet.mockResolvedValue({ data: { summary: { status: 'up' } }, error: null, status: 200 });
});

describe('the MCP uptime proxy', () => {
  test('proxies to the tenant-scoped REST uptime route', async () => {
    const res = await GET(request(), ctx(EP));
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ summary: { status: 'up' } });
    expect(proxyRestGet.mock.calls[0][1]).toBe(`/mcp/acme/endpoints/${EP}/uptime`);
  });

  test('forwards window_hours and limit, and nothing else', async () => {
    await GET(request('?window_hours=6&limit=1&tenant=other'), ctx(EP));
    expect(proxyRestGet.mock.calls[0][1]).toBe(
      `/mcp/acme/endpoints/${EP}/uptime?window_hours=6&limit=1`,
    );
  });

  test('rejects a non-integer query value and a non-UUID id without calling upstream', async () => {
    expect((await GET(request('?limit=abc'), ctx(EP))).status).toBe(400);
    expect((await GET(request(), ctx('../../admin'))).status).toBe(400);
    expect(proxyRestGet).not.toHaveBeenCalled();
  });

  test('keeps the upstream error status', async () => {
    proxyRestGet.mockResolvedValue({ data: null, error: 'MCP endpoint not found', status: 404 });
    const res = await GET(request(), ctx(EP));
    expect(res.status).toBe(404);
    expect(await res.json()).toEqual({ success: false, error: 'MCP endpoint not found' });
  });
});
