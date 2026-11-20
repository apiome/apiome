/**
 * @jest-environment node
 */
/**
 * `$ref` hygiene BFF routes — COA-2.8 (#7051).
 *
 * Each route forwards to apiome-rest for the session's tenant, keeps the query (`version`, `url`)
 * and passes a refusal's `code` through.
 */

import { jest } from '@jest/globals';
import { NextRequest } from 'next/server';

type Proxy = (...args: unknown[]) => Promise<Record<string, unknown>>;
const proxyRestGet = jest.fn<Proxy>();
const proxyRestPost = jest.fn<Proxy>();
const proxyRestPut = jest.fn<Proxy>();
const proxyRestDelete = jest.fn<Proxy>();

jest.mock('@lib/primitives-api-proxy', () => ({
  getAuthenticatedTenantContext: async () => ({ ok: true, tenantSlug: 'acme', user: { id: 'u-1' } }),
  proxyRestGet: (...args: unknown[]) => proxyRestGet(...args),
  proxyRestPost: (...args: unknown[]) => proxyRestPost(...args),
  proxyRestPut: (...args: unknown[]) => proxyRestPut(...args),
  proxyRestDelete: (...args: unknown[]) => proxyRestDelete(...args),
}));

import { GET as listGet } from '../src/app/api/projects/[projectId]/references/route';
import { POST as refreshPost } from '../src/app/api/projects/[projectId]/references/refresh/route';
import { DELETE as pinDelete, PUT as pinPut } from '../src/app/api/projects/[projectId]/references/pin/route';
import { GET as policyGet, PUT as policyPut } from '../src/app/api/external-ref-policy/route';

const USER = { id: 'u-1' };
const params = { params: Promise.resolve({ projectId: 'p-1' }) };
const base = '/projects/acme/p-1/references';

function request(url: string, method = 'GET', body?: unknown): NextRequest {
  return new NextRequest(`http://x${url}`, { method, body: body === undefined ? undefined : JSON.stringify(body) });
}

beforeEach(() => {
  for (const mock of [proxyRestGet, proxyRestPost, proxyRestPut, proxyRestDelete]) {
    mock.mockReset();
    mock.mockResolvedValue({ data: { ok: true }, status: 200, error: null });
  }
});

test('list keeps the version query', async () => {
  const response = await listGet(request('/api/projects/p-1/references?version=1.0.0'), params);
  expect(response.status).toBe(200);
  expect(proxyRestGet).toHaveBeenCalledWith(USER, `${base}?version=1.0.0`);
});

test('refresh and pin forward their bodies; unpin needs a url', async () => {
  await refreshPost(request('/api/projects/p-1/references/refresh', 'POST', { urls: ['https://a/x.json'] }), params);
  expect(proxyRestPost).toHaveBeenCalledWith(USER, `${base}/refresh`, { urls: ['https://a/x.json'] });
  await pinPut(request('/api/projects/p-1/references/pin', 'PUT', { url: 'https://a/x.json' }), params);
  expect(proxyRestPut).toHaveBeenCalledWith(USER, `${base}/pin`, { url: 'https://a/x.json' });
  await pinDelete(request('/api/projects/p-1/references/pin?url=https%3A%2F%2Fa%2Fx.json', 'DELETE'), params);
  expect(proxyRestDelete).toHaveBeenCalledWith(USER, `${base}/pin?url=https%3A%2F%2Fa%2Fx.json`);
  const missing = await pinDelete(request('/api/projects/p-1/references/pin', 'DELETE'), params);
  expect(missing.status).toBe(400);
});

test('a refusal code is passed through', async () => {
  proxyRestPut.mockResolvedValue({
    data: null,
    error: 'Refresh this reference before pinning it.',
    status: 409,
    detail: { code: 'ref-not-fetched', message: 'Refresh this reference before pinning it.' },
  });
  const response = await pinPut(request('/api/projects/p-1/references/pin', 'PUT', { url: 'u' }), params);
  expect(response.status).toBe(409);
  expect(await response.json()).toMatchObject({ success: false, code: 'ref-not-fetched' });
});

test('the policy routes forward to the tenant governance path', async () => {
  await policyGet();
  expect(proxyRestGet).toHaveBeenCalledWith(USER, '/tenants/acme/governance/external-ref-policy');
  await policyPut(request('/api/external-ref-policy', 'PUT', { mode: 'inline', allowlist: [] }));
  expect(proxyRestPut).toHaveBeenCalledWith(USER, '/tenants/acme/governance/external-ref-policy', {
    mode: 'inline',
    allowlist: [],
  });
});
