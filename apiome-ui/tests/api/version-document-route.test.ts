/**
 * @jest-environment node
 *
 * The rendered-document proxy (COA-5.13, #7089): the tenant comes from the session, the request is
 * forwarded to `GET /v1/versions/{tenant}/{project}/{version}/document` with its `If-None-Match`,
 * the body and the cache headers come back untouched (304 included), and a refusal keeps REST's
 * status with its `code`. Nothing is generated and Postgres is not read.
 */

import { beforeEach, describe, expect, jest, test } from '@jest/globals';

const mockContext = jest.fn(async (): Promise<unknown> => ({
  ok: true,
  user: { user_id: 'u-1', email: 'ada@acme.io' },
  tenantSlug: 'acme',
}));

jest.mock('@lib/primitives-api-proxy', () => ({
  getAuthenticatedTenantContext: () => mockContext(),
}));

jest.mock('@lib/rest-auth', () => ({
  createRestAuthHeaders: jest.fn(() => ({
    Authorization: 'Bearer test-token',
    'Content-Type': 'application/json',
  })),
  REST_API_BASE_URL: 'http://rest.test/v1',
}));

// The route must not reach the database layer at all.
jest.mock('@lib/db/helper', () => {
  throw new Error('the document route must not import the database helper');
});

import { NextRequest } from 'next/server';
import { GET } from '@/app/api/versions/[versionId]/document/route';

const PROJECT = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const VERSION = '22222222-2222-4222-8222-222222222222';
const BODY = '{"openapi":"3.2.0","paths":{}}';

let upstream: { url: string; headers: Record<string, string> }[] = [];
let reply: () => Response;

beforeEach(() => {
  upstream = [];
  mockContext.mockClear();
  reply = () =>
    new Response(BODY, {
      status: 200,
      headers: {
        'content-type': 'application/json',
        etag: '"abc"',
        'cache-control': 'private, no-cache',
        'x-apiome-content-sha256': 'abc',
        'x-apiome-document-cache': 'hit',
        'x-internal': 'dropped',
      },
    });
  global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    upstream.push({ url: String(input), headers: (init?.headers ?? {}) as Record<string, string> });
    return reply();
  }) as unknown as typeof fetch;
});

function get(query: string, headers: Record<string, string> = {}, versionId = VERSION) {
  const request = new NextRequest(`http://ui.test/api/versions/${versionId}/document?${query}`, {
    headers,
  });
  return GET(request, { params: Promise.resolve({ versionId }) });
}

describe('GET /api/versions/[versionId]/document', () => {
  test('streams the stored document with its digest and cache status', async () => {
    const response = await get(`projectId=${PROJECT}`);

    expect(response.status).toBe(200);
    expect(await response.text()).toBe(BODY);
    expect(upstream).toHaveLength(1);
    expect(upstream[0].url).toBe(
      `http://rest.test/v1/versions/acme/${PROJECT}/${VERSION}/document`,
    );
    expect(upstream[0].headers.Authorization).toBe('Bearer test-token');
    expect(upstream[0].headers['Content-Type']).toBeUndefined();
    expect(response.headers.get('etag')).toBe('"abc"');
    expect(response.headers.get('x-apiome-content-sha256')).toBe('abc');
    expect(response.headers.get('x-apiome-document-cache')).toBe('hit');
    expect(response.headers.get('cache-control')).toBe('private, no-cache');
    expect(response.headers.get('x-internal')).toBeNull();
  });

  test('forwards If-None-Match and passes a 304 back with no body', async () => {
    reply = () =>
      new Response(null, {
        status: 304,
        headers: { etag: '"abc"', 'x-apiome-content-sha256': 'abc' },
      });

    const response = await get(`projectId=${PROJECT}`, {
      'if-none-match': '"abc"',
      range: 'bytes=0-9',
    });

    expect(upstream[0].headers['if-none-match']).toBe('"abc"');
    // A document is always read whole: Range is not forwarded.
    expect(upstream[0].headers.range).toBeUndefined();
    expect(response.status).toBe(304);
    expect(await response.text()).toBe('');
    expect(response.headers.get('etag')).toBe('"abc"');
  });

  test.each([
    ['a missing project', 'projectId=', VERSION],
    ['a project that is not a UUID', 'projectId=../../tenants', VERSION],
    ['a version that is not a UUID', `projectId=${PROJECT}`, 'latest'],
  ])('refuses %s before calling REST', async (_name, query, versionId) => {
    const response = await get(query, {}, versionId);
    expect(response.status).toBe(400);
    expect(await response.json()).toEqual({
      success: false,
      error: 'A project and version id are required.',
    });
    expect(upstream).toHaveLength(0);
    expect(mockContext).not.toHaveBeenCalled();
  });

  test('answers with the session failure when nobody is signed in', async () => {
    mockContext.mockResolvedValueOnce({ ok: false, error: 'Unauthorized', status: 401 });
    const response = await get(`projectId=${PROJECT}`);
    expect(response.status).toBe(401);
    expect(await response.json()).toEqual({ success: false, error: 'Unauthorized' });
    expect(upstream).toHaveLength(0);
  });

  test("keeps REST's refusal, with its message and code", async () => {
    reply = () =>
      new Response(
        JSON.stringify({
          detail: {
            code: 'document-unreadable',
            message: 'The document store did not return the document.',
          },
        }),
        { status: 502, headers: { 'content-type': 'application/json' } },
      );
    const response = await get(`projectId=${PROJECT}`);
    expect(response.status).toBe(502);
    expect(await response.json()).toEqual({
      success: false,
      error: 'The document store did not return the document.',
      code: 'document-unreadable',
    });
  });

  test('passes a plain 404 or 403 detail through', async () => {
    reply = () =>
      new Response(JSON.stringify({ detail: 'Version not found: x' }), {
        status: 404,
        headers: { 'content-type': 'application/json' },
      });
    const response = await get(`projectId=${PROJECT}`);
    expect(response.status).toBe(404);
    expect(await response.json()).toEqual({ success: false, error: 'Version not found: x' });
  });

  test('names the status when REST sent no JSON', async () => {
    reply = () =>
      new Response('upstream exploded', { status: 500, headers: { 'content-type': 'text/plain' } });
    const response = await get(`projectId=${PROJECT}`);
    expect(response.status).toBe(500);
    expect(await response.json()).toEqual({
      success: false,
      error: 'The document could not be read (HTTP 500).',
    });
  });

  test('answers 502 when REST cannot be reached', async () => {
    global.fetch = jest.fn(async () => {
      throw new TypeError('fetch failed');
    }) as unknown as typeof fetch;
    const response = await get(`projectId=${PROJECT}`);
    expect(response.status).toBe(502);
    expect(await response.json()).toEqual({
      success: false,
      error: 'apiome-rest could not be reached.',
    });
  });
});
