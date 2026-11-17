/**
 * @jest-environment node
 *
 * The Single sign-on BFF routes — EID-1.2 (#5012).
 *
 * `/api/workspace-sso/[[...path]]` drives the real handlers with the tenant context and the
 * upstream `fetch` mocked: the tenant comes from the session, only the path shapes REST defines
 * are forwarded, a refusal keeps REST's status and its stable `sso-*` code, a write clears the
 * routable-provider cache (so disabling stops routing at once) and a read does not.
 *
 * `/api/login/sso-domain` answers from the routable set only: a verified domain of an enabled
 * provider is `true`; anything else, and any failure, is `false`.
 */

import { beforeEach, describe, expect, jest, test } from '@jest/globals';

const mockInvalidate = jest.fn();
const mockResolve = jest.fn<() => Promise<{ providers: Array<{ domains: string[] }>; fingerprint: string }>>();

jest.mock('@lib/primitives-api-proxy', () => ({
  getAuthenticatedTenantContext: jest.fn(async () => mockContext),
}));

jest.mock('@lib/rest-auth', () => ({
  createRestAuthHeaders: jest.fn(() => ({ Authorization: 'Bearer test-token' })),
  REST_API_BASE_URL: 'http://rest.test/v1',
}));

jest.mock('@lib/auth/sso-provider-resolver', () => ({
  invalidateSsoProviderCache: () => mockInvalidate(),
  resolveSsoProviders: () => mockResolve(),
}));

import { NextRequest } from 'next/server';
import { DELETE, GET, PATCH, POST } from '@/app/api/workspace-sso/[[...path]]/route';
import { POST as lookUp } from '@/app/api/login/sso-domain/route';

const ID = '8dc47ff5-488b-44d0-9d72-ebf5ad0de3b2';

let mockContext: unknown;
let upstream: Array<{ url: string; method: string; body: unknown; contentType: string | undefined }> = [];
let reply: { status: number; body: unknown } = { status: 200, body: {} };

beforeEach(() => {
  mockInvalidate.mockReset();
  mockResolve.mockReset();
  mockContext = { ok: true, user: { user_id: 'u-1', email: 'ada@acme.io' }, tenantSlug: 'acme' };
  upstream = [];
  reply = { status: 200, body: { providers: [] } };
  global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    upstream.push({
      url: String(input),
      method: init?.method ?? 'GET',
      body: init?.body ? JSON.parse(String(init.body)) : undefined,
      contentType: (init?.headers as Record<string, string> | undefined)?.['Content-Type'],
    });
    return new Response(JSON.stringify(reply.body), { status: reply.status });
  }) as unknown as typeof fetch;
});

const request = (method: string, body?: unknown) =>
  new NextRequest('http://ui.test/api/workspace-sso', {
    method,
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
const ctx = (...path: string[]) => ({ params: Promise.resolve({ path }) });

describe('/api/workspace-sso', () => {
  test('GET lists the session tenant’s providers and leaves the cache alone', async () => {
    const response = await GET(request('GET'), ctx());
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ providers: [] });
    expect(upstream).toEqual([
      { url: 'http://rest.test/v1/tenants/acme/sso/providers', method: 'GET', body: undefined, contentType: undefined },
    ]);
    expect(mockInvalidate).not.toHaveBeenCalled();
  });

  test('POST relays the body verbatim and clears the routable cache', async () => {
    reply = { status: 201, body: { id: ID } };
    const body = { protocol: 'oidc', slug: 'acme-okta', client_secret: 's3cret' };
    const response = await POST(request('POST', body), ctx());
    expect(response.status).toBe(201);
    expect(upstream[0]).toMatchObject({ method: 'POST', body, contentType: 'application/json' });
    expect(mockInvalidate).toHaveBeenCalledTimes(1);
  });

  test('PATCH {enabled:false} clears the cache, so disabling stops routing at once', async () => {
    await PATCH(request('PATCH', { enabled: false }), ctx(ID));
    expect(upstream[0]).toMatchObject({
      url: `http://rest.test/v1/tenants/acme/sso/providers/${ID}`,
      method: 'PATCH',
      body: { enabled: false },
    });
    expect(mockInvalidate).toHaveBeenCalledTimes(1);
  });

  test('verify and domain removal reach their REST paths', async () => {
    await POST(request('POST'), ctx(ID, 'domains', 'acme.com', 'verify'));
    await DELETE(request('DELETE'), ctx(ID, 'domains', 'acme.com'));
    expect(upstream.map((call) => `${call.method} ${call.url}`)).toEqual([
      `POST http://rest.test/v1/tenants/acme/sso/providers/${ID}/domains/acme.com/verify`,
      `DELETE http://rest.test/v1/tenants/acme/sso/providers/${ID}/domains/acme.com`,
    ]);
  });

  test('a path REST does not define is refused here and never forwarded', async () => {
    const response = await GET(request('GET'), ctx('..', '..', 'members'));
    expect(response.status).toBe(404);
    expect(upstream).toEqual([]);
  });

  test('a refusal keeps REST’s status, message and stable code — and the cache', async () => {
    reply = {
      status: 409,
      body: { detail: { error: 'sso-domain-claimed', message: 'acme.com is already verified for another workspace.' } },
    };
    const response = await POST(request('POST', { domain: 'acme.com' }), ctx(ID, 'domains'));
    expect(response.status).toBe(409);
    expect(await response.json()).toEqual({
      success: false,
      error: 'acme.com is already verified for another workspace.',
      code: 'sso-domain-claimed',
    });
    expect(mockInvalidate).not.toHaveBeenCalled();
  });

  test('a member who is not an admin sees REST’s 403', async () => {
    reply = { status: 403, body: { detail: 'Only tenant administrators can perform this action' } };
    const response = await GET(request('GET'), ctx());
    expect(response.status).toBe(403);
    expect((await response.json()).error).toBe('Only tenant administrators can perform this action');
  });

  test('no session, no call', async () => {
    mockContext = { ok: false, status: 401, error: 'Unauthorized' };
    const response = await GET(request('GET'), ctx());
    expect(response.status).toBe(401);
    expect(upstream).toEqual([]);
  });

  test('an unreachable REST API is a 503 with a plain message', async () => {
    global.fetch = jest.fn(async () => {
      throw new Error('ECONNREFUSED');
    }) as unknown as typeof fetch;
    const response = await GET(request('GET'), ctx());
    expect(response.status).toBe(503);
    expect((await response.json()).error).toMatch(/unavailable/);
  });
});

describe('/api/login/sso-domain', () => {
  const ask = (body: unknown) =>
    lookUp(new NextRequest('http://ui.test/api/login/sso-domain', { method: 'POST', body: JSON.stringify(body) }));

  beforeEach(() => {
    mockResolve.mockResolvedValue({ providers: [{ domains: ['acme.com'] }], fingerprint: 'f' });
  });

  test('a verified domain of an enabled provider routes to SSO', async () => {
    expect(await (await ask({ email: 'Ada@Acme.com' })).json()).toEqual({ sso: true });
  });

  test('any other domain does not — including a subdomain and a look-alike', async () => {
    for (const email of ['ada@other.com', 'ada@mail.acme.com', 'ada@acme.com.evil.io', 'ada@notacme.com']) {
      expect(await (await ask({ email })).json()).toEqual({ sso: false });
    }
  });

  test('says nothing more than yes or no', async () => {
    const body = await (await ask({ email: 'ada@acme.com' })).json();
    expect(Object.keys(body)).toEqual(['sso']);
  });

  test('a half-typed or malformed address is not looked up', async () => {
    for (const body of [{ email: 'ada@acme' }, { email: 42 }, {}, null]) {
      expect(await (await ask(body)).json()).toEqual({ sso: false });
    }
    expect(mockResolve).not.toHaveBeenCalled();
  });

  test('a failed read answers no, leaving the password path', async () => {
    mockResolve.mockRejectedValue(new Error('down'));
    expect(await (await ask({ email: 'ada@acme.com' })).json()).toEqual({ sso: false });
  });
});
