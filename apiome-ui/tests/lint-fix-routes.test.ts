/**
 * @jest-environment node
 */
/**
 * Lint-fix BFF routes — GVM-3.6 (#5874).
 *
 * The plan route forwards to the REST plan and adds `published` from the version read; the apply
 * route forwards only `fixIds` and `reason`, refuses an empty request, and passes a refusal's
 * `detail: { code, message }` through with its status.
 */

import { jest } from '@jest/globals';
import { NextRequest } from 'next/server';

jest.mock('@lib/rest-auth', () => ({
  createRestAuthHeaders: () => ({ 'Content-Type': 'application/json', Authorization: 'Bearer t' }),
  getRestApiBaseUrl: () => 'http://rest/v1',
  REST_API_BASE_URL: 'http://rest/v1',
}));
jest.mock('@lib/auth/server-session', () => ({
  getAuthSession: async () => ({ user: { user_id: 'u-1', current_tenant_id: 't-1' } }),
}));
jest.mock('@lib/db/helper', () => ({
  getTenantById: async () => ({ id: 't-1', slug: 'acme' }),
}));

import { GET as planGet } from '../src/app/api/projects/[projectId]/versions/[versionId]/lint/fixes/route';
import { POST as applyPost } from '../src/app/api/projects/[projectId]/versions/[versionId]/lint/fixes/apply/route';

const params = { params: Promise.resolve({ projectId: 'p-1', versionId: 'v-1' }) };
const originalFetch = global.fetch;

/** A fetch reply. */
function reply(body: unknown, status = 200) {
  return { ok: status < 400, status, json: async () => body } as unknown as Response;
}

afterEach(() => {
  global.fetch = originalFetch;
});

test('plan forwards to REST and adds published from the version read', async () => {
  const fetchMock = jest.fn(async (url: unknown) =>
    String(url).endsWith('/lint/fixes?format=json')
      ? reply({ entries: [], counts: { ready: 0 } })
      : reply({ id: 'v-1', published: true }),
  );
  global.fetch = fetchMock as unknown as typeof fetch;
  const response = await planGet(new NextRequest('http://x/api'), params);
  expect(response.status).toBe(200);
  expect(await response.json()).toEqual({
    success: true,
    entries: [],
    counts: { ready: 0 },
    published: true,
  });
  expect(fetchMock.mock.calls.map(([url]) => String(url))).toEqual([
    'http://rest/v1/versions/acme/p-1/v-1/lint/fixes?format=json',
    'http://rest/v1/versions/acme/p-1/v-1',
  ]);
});

test('plan passes a refusal through, and a failed version read leaves published false', async () => {
  global.fetch = jest.fn(async (url: unknown) =>
    String(url).includes('/lint/fixes')
      ? reply({ detail: { code: 'lint-fix-not-openapi', message: 'OpenAPI 3.x only.' } }, 422)
      : reply({}, 500),
  ) as unknown as typeof fetch;
  const refused = await planGet(new NextRequest('http://x/api'), params);
  expect(refused.status).toBe(422);
  expect(await refused.json()).toMatchObject({
    success: false,
    detail: { code: 'lint-fix-not-openapi' },
  });

  global.fetch = jest.fn(async (url: unknown) =>
    String(url).includes('/lint/fixes') ? reply({ entries: [] }) : reply({}, 500),
  ) as unknown as typeof fetch;
  const ok = await planGet(new NextRequest('http://x/api'), params);
  expect(await ok.json()).toMatchObject({ success: true, published: false });
});

test('apply forwards only fixIds and reason', async () => {
  const fetchMock = jest.fn<(url: string, init?: RequestInit) => Promise<Response>>(async () =>
    reply({ versionRecordId: 'v-2', versionLabel: '1.0.1' }, 201),
  );
  global.fetch = fetchMock as unknown as typeof fetch;
  const response = await applyPost(
    new NextRequest('http://x/api', {
      method: 'POST',
      body: JSON.stringify({
        fixIds: ['fix-a', 3],
        reason: '  tidy ',
        rules: ['x'],
        includeRenames: true,
      }),
    }),
    params,
  );
  expect(response.status).toBe(200);
  const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
  expect(url).toBe('http://rest/v1/versions/acme/p-1/v-1/lint/fixes/apply?tenant_slug=acme');
  expect(JSON.parse(String(init.body))).toEqual({ fixIds: ['fix-a'], reason: 'tidy' });
});

test('apply refuses a request without fixes or a reason', async () => {
  const fetchMock = jest.fn();
  global.fetch = fetchMock as unknown as typeof fetch;
  const response = await applyPost(
    new NextRequest('http://x/api', {
      method: 'POST',
      body: JSON.stringify({ fixIds: [], reason: 'x' }),
    }),
    params,
  );
  expect(response.status).toBe(400);
  expect(fetchMock).not.toHaveBeenCalled();
});

test('apply passes a published refusal through with its code', async () => {
  global.fetch = jest.fn(async () =>
    reply({ detail: { code: 'lint-fix-version-published', message: 'Published.' } }, 409),
  ) as unknown as typeof fetch;
  const response = await applyPost(
    new NextRequest('http://x/api', {
      method: 'POST',
      body: JSON.stringify({ fixIds: ['fix-a'], reason: 'x' }),
    }),
    params,
  );
  expect(response.status).toBe(409);
  expect(await response.json()).toMatchObject({
    success: false,
    detail: { code: 'lint-fix-version-published', message: 'Published.' },
  });
});
