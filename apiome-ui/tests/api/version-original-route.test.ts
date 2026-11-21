/**
 * @jest-environment node
 *
 * The original-download proxy (COA-5.7, #7083): the tenant comes from the session, the request is
 * forwarded to `GET /v1/versions/{tenant}/{project}/{version}/original[/{part}]` with its `Range` /
 * `If-None-Match`, the body and the download headers come back untouched (206 included), and a
 * refusal keeps REST's status with its `code`.
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
  createRestAuthHeaders: jest.fn(() => ({ Authorization: 'Bearer test-token', 'Content-Type': 'application/json' })),
  REST_API_BASE_URL: 'http://rest.test/v1',
}));

import { NextRequest } from 'next/server';
import { GET } from '@/app/api/versions/[versionId]/original/route';

const PROJECT = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const VERSION = '22222222-2222-4222-8222-222222222222';

let upstream: { url: string; headers: Record<string, string> }[] = [];
let reply: () => Response;

beforeEach(() => {
  upstream = [];
  reply = () =>
    new Response('openapi: 3.1.0\n', {
      status: 200,
      headers: {
        'content-type': 'application/yaml',
        'content-disposition': 'attachment; filename="pets.yaml"',
        etag: '"abc"',
        'x-apiome-content-sha256': 'abc',
        'x-internal': 'dropped',
      },
    });
  global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    upstream.push({ url: String(input), headers: (init?.headers ?? {}) as Record<string, string> });
    return reply();
  }) as unknown as typeof fetch;
});

function get(query: string, headers: Record<string, string> = {}) {
  const request = new NextRequest(`http://ui.test/api/versions/${VERSION}/original?${query}`, { headers });
  return GET(request, { params: Promise.resolve({ versionId: VERSION }) });
}

describe('GET /api/versions/[versionId]/original', () => {
  test('streams the original with its download headers', async () => {
    const response = await get(`projectId=${PROJECT}`);

    expect(response.status).toBe(200);
    expect(await response.text()).toBe('openapi: 3.1.0\n');
    expect(response.headers.get('content-disposition')).toBe('attachment; filename="pets.yaml"');
    expect(response.headers.get('x-apiome-content-sha256')).toBe('abc');
    expect(response.headers.get('x-internal')).toBeNull();
    expect(upstream[0].url).toBe(`http://rest.test/v1/versions/acme/${PROJECT}/${VERSION}/original`);
    expect(upstream[0].headers.Authorization).toBe('Bearer test-token');
    expect(upstream[0].headers['Content-Type']).toBeUndefined();
  });

  test('forwards Range and passes the 206 through', async () => {
    reply = () => new Response('openapi', { status: 206, headers: { 'content-range': 'bytes 0-6/15' } });

    const response = await get(`projectId=${PROJECT}`, { Range: 'bytes=0-6', 'If-None-Match': '"x"' });

    expect(response.status).toBe(206);
    expect(response.headers.get('content-range')).toBe('bytes 0-6/15');
    expect(upstream[0].headers.range).toBe('bytes=0-6');
    expect(upstream[0].headers['if-none-match']).toBe('"x"');
  });

  test('addresses one file of a set, each segment encoded', async () => {
    await get(`projectId=${PROJECT}&part=${encodeURIComponent('/api/schemas/pet v2.json')}`);

    expect(upstream[0].url).toBe(
      `http://rest.test/v1/versions/acme/${PROJECT}/${VERSION}/original/api/schemas/pet%20v2.json`,
    );
  });

  test('keeps a refusal’s status and code', async () => {
    reply = () =>
      new Response(JSON.stringify({ detail: { code: 'original-withheld', message: 'Withheld.' } }), {
        status: 410,
        headers: { 'content-type': 'application/json' },
      });

    const response = await get(`projectId=${PROJECT}`);

    expect(response.status).toBe(410);
    expect(await response.json()).toEqual({ success: false, error: 'Withheld.', code: 'original-withheld' });
  });

  test('refuses a malformed id before calling REST', async () => {
    const response = await get('projectId=nope');

    expect(response.status).toBe(400);
    expect(upstream).toHaveLength(0);
  });
});
