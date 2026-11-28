/**
 * @jest-environment node
 */
/**
 * The BFF of the Migration wizard — PFX-8.16 (#7313): `/api/pact/migrations` (list, start),
 * `/api/pact/migrations/test`, and `/api/pact/migrations/{id}` (read, `stop`, `resume`).
 *
 * * a malformed run id is a 404 and an unknown parameter or field a 400 naming it — REST is not called;
 * * a checked call is forwarded as the signed-in user to the workspace's `pact-migration` path, the
 *   source's credentials passing through untouched;
 * * REST's refusal keeps its status.
 */

import { NextResponse } from 'next/server';

const forwarded: Array<{ url: string; method: string; body?: unknown }> = [];
let restAnswer: () => NextResponse = () => NextResponse.json({ ok: true });

jest.mock('@lib/connectors-proxy', () => ({
  resolveConnectorTenant: async () => ({ user: { user_id: 'u-1' }, slug: 'acme' }),
  tenantUrl: (slug: string, path: string) => `http://rest/v1/tenants/${slug}/${path}`,
  forwardConnectorRequest: async (url: string, init: { method: string; body?: unknown }) => {
    forwarded.push({ url, method: init.method, body: init.body });
    return restAnswer();
  },
}));
jest.mock('@lib/rest-auth', () => ({
  createRestAuthHeaders: () => ({ Authorization: 'Bearer session' }),
  REST_API_BASE_URL: 'http://rest/v1',
}));

import { GET as listRuns, POST as startRun } from '../src/app/api/pact/migrations/route';
import { POST as testSource } from '../src/app/api/pact/migrations/test/route';
import { GET as readRun } from '../src/app/api/pact/migrations/[runId]/route';
import { POST as stopRun } from '../src/app/api/pact/migrations/[runId]/stop/route';
import { POST as resumeRun } from '../src/app/api/pact/migrations/[runId]/resume/route';

const RUN_ID = '6f9c2d1e-0b7a-4c3e-9a51-2f8e7d6c5b4a';
const BASE = 'http://rest/v1/tenants/acme/pact-migration';
const TOKEN = 's3cr3t-read-token';
const params = (runId: string) => ({ params: Promise.resolve({ runId }) });

async function request(url: string, body?: unknown, method = 'POST') {
  const { NextRequest } = await import('next/server');
  return new NextRequest(`http://localhost${url}`, {
    method,
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
}

beforeEach(() => {
  forwarded.length = 0;
  restAnswer = () => NextResponse.json({ ok: true });
});

describe('the list and start', () => {
  it('lists the runs and takes no parameter', async () => {
    expect((await listRuns(await request('/api/pact/migrations', undefined, 'GET'))).status).toBe(200);
    expect(forwarded).toEqual([{ url: `${BASE}/runs`, method: 'GET', body: undefined }]);
    const refused = await listRuns(await request('/api/pact/migrations?limit=5', undefined, 'GET'));
    expect(refused.status).toBe(400);
    expect((await refused.json()).error).toContain('limit');
    expect(forwarded).toHaveLength(1);
  });

  it('starts a run with the body as checked, credentials included', async () => {
    const body = { source: 'https://acme.pactflow.io', token: TOKEN, mode: 'copy', options: { conflicts: 'replace' } };
    expect((await startRun(await request('/api/pact/migrations', body))).status).toBe(200);
    expect(forwarded).toEqual([{ url: `${BASE}/runs`, method: 'POST', body }]);
  });

  it.each([
    [{ source: 'https://acme.pactflow.io', token: TOKEN }, 'mode is dry-run or copy.'],
    [{ source: 'file:///etc/passwd', mode: 'copy' }, 'The URL must start with http:// or https://.'],
    [{ source: 'https://acme.pactflow.io', mode: 'copy', options: { teams: true } }, 'Unsupported option teams.'],
    ['not json', 'Send the run as a JSON object.'],
  ])('refuses %j without calling REST', async (body, error) => {
    const answer = await startRun(await request('/api/pact/migrations', body));
    expect(answer.status).toBe(400);
    expect(await answer.json()).toEqual({ success: false, error });
    expect(forwarded).toEqual([]);
  });

  it('passes on REST’s refusal with its status', async () => {
    restAnswer = () => NextResponse.json({ success: false, error: 'this workspace already has a migration running' }, { status: 409 });
    const answer = await startRun(await request('/api/pact/migrations', { source: 'https://b.example', mode: 'dry-run' }));
    expect(answer.status).toBe(409);
  });
});

describe('the connection test', () => {
  it('forwards a checked source', async () => {
    const body = { source: 'https://b.example', username: 'ci', password: 'pw' };
    expect((await testSource(await request('/api/pact/migrations/test', body))).status).toBe(200);
    expect(forwarded).toEqual([{ url: `${BASE}/test`, method: 'POST', body }]);
  });

  it('refuses an unknown field by name', async () => {
    const answer = await testSource(await request('/api/pact/migrations/test', { source: 'https://b.example', mode: 'copy' }));
    expect(answer.status).toBe(400);
    expect((await answer.json()).error).toBe('Unsupported field mode.');
    expect(forwarded).toEqual([]);
  });
});

describe('one run', () => {
  it('reads it from a log cursor', async () => {
    expect((await readRun(await request(`/api/pact/migrations/${RUN_ID}?after=41`, undefined, 'GET'), params(RUN_ID))).status).toBe(200);
    expect(forwarded).toEqual([{ url: `${BASE}/runs/${RUN_ID}?after=41`, method: 'GET', body: undefined }]);
  });

  it('refuses a bad cursor or parameter with a 400', async () => {
    for (const query of ['after=x', 'log_after=3']) {
      const answer = await readRun(await request(`/api/pact/migrations/${RUN_ID}?${query}`, undefined, 'GET'), params(RUN_ID));
      expect(answer.status).toBe(400);
    }
    expect(forwarded).toEqual([]);
  });

  it('stops it with no body', async () => {
    expect((await stopRun(await request(`/api/pact/migrations/${RUN_ID}/stop`), params(RUN_ID))).status).toBe(200);
    expect(forwarded).toEqual([{ url: `${BASE}/runs/${RUN_ID}/stop`, method: 'POST', body: undefined }]);
  });

  it('resumes it with the credentials again, and nothing else', async () => {
    expect((await resumeRun(await request(`/api/pact/migrations/${RUN_ID}/resume`, { token: TOKEN }), params(RUN_ID))).status).toBe(200);
    expect(forwarded).toEqual([{ url: `${BASE}/runs/${RUN_ID}/resume`, method: 'POST', body: { token: TOKEN } }]);
    const refused = await resumeRun(
      await request(`/api/pact/migrations/${RUN_ID}/resume`, { token: TOKEN, source: 'https://evil.example' }),
      params(RUN_ID),
    );
    expect(refused.status).toBe(400);
    expect(forwarded).toHaveLength(1);
  });

  it('answers 404 for a malformed run id without calling REST', async () => {
    const bad = '..%2Fimport';
    expect((await readRun(await request(`/api/pact/migrations/${bad}`, undefined, 'GET'), params('../import'))).status).toBe(404);
    expect((await stopRun(await request(`/api/pact/migrations/${bad}/stop`), params('../import'))).status).toBe(404);
    expect((await resumeRun(await request(`/api/pact/migrations/${bad}/resume`, {}), params('../import'))).status).toBe(404);
    expect(forwarded).toEqual([]);
  });
});

describe('keep-in-sync (PFX-8.17)', () => {
  it('reads and switches a run’s keep-in-sync, credentials passing through', async () => {
    const { GET: readSync, PUT: switchSync } = await import('../src/app/api/pact/migrations/[runId]/sync/route');
    const url = `/api/pact/migrations/${RUN_ID}/sync`;
    expect((await readSync(await request(url, undefined, 'GET'), params(RUN_ID))).status).toBe(200);
    const on = { enabled: true, token: TOKEN, interval_minutes: 15 };
    expect((await switchSync(await request(url, on, 'PUT'), params(RUN_ID))).status).toBe(200);
    expect((await switchSync(await request(url, { enabled: false }, 'PUT'), params(RUN_ID))).status).toBe(200);
    expect(forwarded).toEqual([
      { url: `${BASE}/runs/${RUN_ID}/sync`, method: 'GET', body: undefined },
      { url: `${BASE}/runs/${RUN_ID}/sync`, method: 'PUT', body: on },
      { url: `${BASE}/runs/${RUN_ID}/sync`, method: 'PUT', body: { enabled: false } },
    ]);
  });

  it('refuses a bad id or body without calling REST, and keeps REST’s refusal', async () => {
    const { GET: readSync, PUT: switchSync } = await import('../src/app/api/pact/migrations/[runId]/sync/route');
    expect((await readSync(await request('/x', undefined, 'GET'), params('nope'))).status).toBe(404);
    const url = `/api/pact/migrations/${RUN_ID}/sync`;
    for (const body of [{ enabled: 'yes' }, { enabled: true, schedule: 'hourly' }, { enabled: true, interval_minutes: 1.5 }, null]) {
      const refused = await switchSync(await request(url, body, 'PUT'), params(RUN_ID));
      expect(refused.status).toBe(400);
    }
    expect(forwarded).toHaveLength(0);
    restAnswer = () => NextResponse.json({ success: false, error: 'cannot keep credentials' }, { status: 503 });
    expect((await switchSync(await request(url, { enabled: true, token: TOKEN }, 'PUT'), params(RUN_ID))).status).toBe(503);
  });
});
