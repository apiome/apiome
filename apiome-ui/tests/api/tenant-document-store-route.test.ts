/**
 * @jest-environment node
 *
 * The document storage BFF routes — COA-5.15 (#7092).
 *
 * Drives the real handlers with the tenant context and the upstream `fetch` mocked: the tenant comes
 * from the session, `PUT` and `test` forward only the settings fields, `cleanup` forwards a confirm
 * only when the browser gave one, and REST's refusal keeps its status and its reason.
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
import { GET, PUT } from '@/app/api/tenant-document-store/route';
import { POST as TEST } from '@/app/api/tenant-document-store/test/route';
import { POST as CLEANUP } from '@/app/api/tenant-document-store/cleanup/route';

let upstream: Array<{ url: string; method: string; body: unknown }> = [];
let reply: { status: number; body: unknown } = { status: 200, body: {} };

beforeEach(() => {
  upstream = [];
  reply = { status: 200, body: { mode: 'platform', allowed: true } };
  global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    upstream.push({
      url: String(input),
      method: init?.method ?? 'GET',
      body: init?.body ? JSON.parse(String(init.body)) : undefined,
    });
    return new Response(JSON.stringify(reply.body), { status: reply.status });
  }) as unknown as typeof fetch;
});

/** A request to `path` carrying `body` as JSON (or nothing). */
const request = (path: string, method: string, body?: unknown) =>
  new NextRequest(`http://ui.test/api/tenant-document-store${path}`, {
    method,
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });

const BASE = 'http://rest.test/v1/tenants/acme/document-store';

describe('/api/tenant-document-store', () => {
  test('GET reads the session tenant’s settings', async () => {
    const response = await GET();
    expect(response.status).toBe(200);
    expect(upstream).toEqual([{ url: BASE, method: 'GET', body: undefined }]);
  });

  test('PUT forwards the settings and nothing else', async () => {
    await PUT(
      request('', 'PUT', {
        mode: 'tenant',
        credentialId: 'cred-1',
        bucket: 'acme-documents',
        sse: 'kms',
        kmsKeyId: 'alias/docs',
        tenant_id: 'someone-else',
        secretAccessKey: 'never-forwarded',
      })
    );
    expect(upstream[0]).toEqual({
      url: BASE,
      method: 'PUT',
      body: { mode: 'tenant', credentialId: 'cred-1', bucket: 'acme-documents', sse: 'kms', kmsKeyId: 'alias/docs' },
    });
  });

  test('PUT without a valid mode sends an empty body for REST to refuse', async () => {
    await PUT(request('', 'PUT', { mode: 'elsewhere', bucket: 'x' }));
    expect(upstream[0].body).toEqual({});
  });

  test('a REST refusal keeps its status and names the fields', async () => {
    reply = {
      status: 400,
      body: { detail: { code: 'tenant-document-store-invalid', errors: ['bucket: is required to use your own bucket.'] } },
    };
    const response = await PUT(request('', 'PUT', { mode: 'tenant' }));
    expect(response.status).toBe(400);
    expect(await response.json()).toEqual({ success: false, error: 'bucket: is required to use your own bucket.' });
  });

  test('an unavailable bucket keeps its 503 and its reason', async () => {
    reply = {
      status: 503,
      body: { detail: { code: 'tenant-document-store-unavailable', message: 'The bucket is unavailable. AccessDenied.' } },
    };
    const response = await GET();
    expect(response.status).toBe(503);
    expect((await response.json()).error).toBe('The bucket is unavailable. AccessDenied.');
  });
});

describe('/api/tenant-document-store/test', () => {
  test('tests the submitted settings', async () => {
    await TEST(request('/test', 'POST', { mode: 'tenant', bucket: 'acme-documents', credentialId: 'cred-1' }));
    expect(upstream[0]).toEqual({
      url: `${BASE}/test`,
      method: 'POST',
      body: { mode: 'tenant', bucket: 'acme-documents', credentialId: 'cred-1' },
    });
  });

  test('tests the saved settings when nothing is submitted', async () => {
    await TEST(request('/test', 'POST'));
    expect(upstream[0]).toEqual({ url: `${BASE}/test`, method: 'POST', body: undefined });
  });
});

describe('/api/tenant-document-store/cleanup', () => {
  test('forwards the confirm only when it is literally true', async () => {
    await CLEANUP(request('/cleanup', 'POST', { confirm: true }));
    await CLEANUP(request('/cleanup', 'POST', { confirm: 'yes' }));
    await CLEANUP(request('/cleanup', 'POST'));
    expect(upstream.map((call) => call.body)).toEqual([{ confirm: true }, { confirm: false }, { confirm: false }]);
    expect(upstream.every((call) => call.url === `${BASE}/cleanup` && call.method === 'POST')).toBe(true);
  });
});
