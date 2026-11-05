/**
 * @jest-environment node
 *
 * The toolchain check console proxy — MFX-44.6 (#4372).
 *
 * `POST /api/export/verify/tool-checks/{tool}` scopes the run to the session's tenant, forwards only the
 * coordinates REST accepts (never an uploaded artifact), passes REST's NDJSON stream through unbuffered,
 * and turns a refusal into the `{ success: false, error }` envelope with REST's status.
 */

import { beforeEach, describe, expect, jest, test } from '@jest/globals';

jest.mock('@lib/primitives-api-proxy', () => ({
  getAuthenticatedTenantContext: jest.fn(async () => ({
    ok: true,
    user: { user_id: 'u-1', email: 'ada@acme.io' },
    tenantSlug: 'acme',
  })),
  restErrorMessage: (body: { detail?: unknown }) => (typeof body?.detail === 'string' ? body.detail : 'Request failed'),
}));

jest.mock('@lib/rest-auth', () => ({
  createRestAuthHeaders: jest.fn(() => ({ Authorization: 'Bearer test-token' })),
  REST_API_BASE_URL: 'http://rest.test/v1',
}));

import { NextRequest } from 'next/server';
import { getAuthenticatedTenantContext } from '@lib/primitives-api-proxy';
import { POST } from '@/app/api/export/verify/tool-checks/[tool]/route';

const NDJSON = '{"event":"start","command":"buf lint"}\n{"event":"result","status":"passed"}\n';

let upstream: Array<{ url: string; method: string; body: unknown }> = [];
let reply: () => Response = () => new Response(NDJSON, { status: 200 });

beforeEach(() => {
  upstream = [];
  reply = () =>
    new Response(NDJSON, { status: 200, headers: { 'Content-Type': 'application/x-ndjson' } });
  global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    upstream.push({
      url: String(input),
      method: init?.method ?? 'GET',
      body: init?.body ? JSON.parse(String(init.body)) : undefined,
    });
    return reply();
  }) as unknown as typeof fetch;
});

const call = (tool: string, body: unknown) =>
  POST(
    new NextRequest(`http://ui.test/api/export/verify/tool-checks/${tool}`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
    { params: Promise.resolve({ tool }) },
  );

describe('POST /api/export/verify/tool-checks/{tool}', () => {
  test('forwards the coordinates to the tenant-scoped REST route and streams NDJSON back', async () => {
    const response = await call('buf', {
      artifact: 'proj-shop',
      version: null,
      target: 'protobuf',
      options: { package: 'acme.v1' },
      check: 'lint',
      jobId: 'job-1',
      files: { 'evil.proto': 'x' },
    });
    expect(upstream).toEqual([
      {
        url: 'http://rest.test/v1/export/acme/verify/tool-checks/buf',
        method: 'POST',
        body: { artifact: 'proj-shop', version: null, target: 'protobuf', options: { package: 'acme.v1' }, check: 'lint', jobId: 'job-1' },
      },
    ]);
    expect(response.status).toBe(200);
    expect(response.headers.get('content-type')).toBe('application/x-ndjson');
    expect(response.headers.get('x-accel-buffering')).toBe('no');
    expect(await response.text()).toBe(NDJSON);
  });

  test("keeps REST's refusal status and message", async () => {
    reply = () =>
      new Response(JSON.stringify({ detail: 'The buf toolchain is not installed on this server.' }), {
        status: 503,
        headers: { 'Content-Type': 'application/json' },
      });
    const response = await call('buf', { artifact: 'p', target: 'protobuf', check: 'lint' });
    expect(response.status).toBe(503);
    expect(await response.json()).toEqual({ success: false, error: 'The buf toolchain is not installed on this server.' });
  });

  test('refuses a malformed tool key without calling REST', async () => {
    const response = await call('..%2Fadmin', { artifact: 'p', target: 'protobuf', check: 'lint' });
    expect(response.status).toBe(400);
    expect(upstream).toEqual([]);
  });

  test('refuses a missing body', async () => {
    const response = await POST(
      new NextRequest('http://ui.test/api/export/verify/tool-checks/buf', { method: 'POST', body: 'not json' }),
      { params: Promise.resolve({ tool: 'buf' }) },
    );
    expect(response.status).toBe(400);
    expect(upstream).toEqual([]);
  });

  test('passes an unauthenticated session through as its status', async () => {
    (getAuthenticatedTenantContext as jest.Mock).mockImplementationOnce(async () => ({
      ok: false,
      status: 401,
      error: 'Unauthorized',
    }));
    const response = await call('buf', { artifact: 'p', target: 'protobuf', check: 'lint' });
    expect(response.status).toBe(401);
    expect(upstream).toEqual([]);
  });
});
