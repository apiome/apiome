/**
 * @jest-environment node
 */
/**
 * The BFF of the live run and the results upload — PFX-8.9 (#7306):
 * `/api/pact/verification/runs/{id}` (read, `stop`, `rerun`) and `/api/pact/verification/results/upload`.
 *
 * * a malformed run id is a 404 and an unknown parameter or field a 400 naming it — REST is not called;
 * * a checked call is forwarded as the signed-in user to the run's REST path;
 * * the upload sends the report itself, with its media type, to `…/external-verification-results`;
 *   REST's refusal of an unreadable report comes back with its status, reason and pointer;
 * * apiome-rest unreachable is a 503 with the Pact Broker's message.
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

import { GET as readRun } from '../src/app/api/pact/verification/runs/[runId]/route';
import { POST as stopRun } from '../src/app/api/pact/verification/runs/[runId]/stop/route';
import { POST as rerunRun } from '../src/app/api/pact/verification/runs/[runId]/rerun/route';
import { POST as upload } from '../src/app/api/pact/verification/results/upload/route';

const RUN_ID = '6f9c2d1e-0b7a-4c3e-9a51-2f8e7d6c5b4a';
const SHA = 'a'.repeat(64);
const params = (runId: string) => ({ params: Promise.resolve({ runId }) });
const post = (url: string, body?: unknown) =>
  new Request(`http://localhost${url}`, {
    method: 'POST',
    body: body === undefined ? undefined : JSON.stringify(body),
  }) as never;

beforeEach(() => {
  forwarded.length = 0;
  restAnswer = () => NextResponse.json({ ok: true });
});

describe('the run routes', () => {
  it('reads a run from its log cursor', async () => {
    const { NextRequest } = await import('next/server');
    const answer = await readRun(
      new NextRequest(`http://localhost/api/pact/verification/runs/${RUN_ID}?log_after=7`),
      params(RUN_ID),
    );
    expect(answer.status).toBe(200);
    expect(forwarded).toEqual([
      {
        url: `http://rest/v1/tenants/acme/pact-verifier/runs/${RUN_ID}?log_after=7`,
        method: 'GET',
        body: undefined,
      },
    ]);
  });

  it('refuses a malformed id or an unknown parameter without calling REST', async () => {
    const { NextRequest } = await import('next/server');
    expect(
      (
        await readRun(
          new NextRequest('http://localhost/api/pact/verification/runs/x'),
          params('../x'),
        )
      ).status,
    ).toBe(404);
    const unknown = await readRun(
      new NextRequest(`http://localhost/api/pact/verification/runs/${RUN_ID}?tenant=other`),
      params(RUN_ID),
    );
    expect(unknown.status).toBe(400);
    expect((await unknown.json()).error).toBe('tenant is not a parameter of a run read.');
    expect((await stopRun(post('/x'), params('nope'))).status).toBe(404);
    expect((await rerunRun(post('/x', {}), params('nope'))).status).toBe(404);
    expect(forwarded).toEqual([]);
  });

  it('stops a run with no body, and refuses one', async () => {
    expect((await stopRun(post('/stop', { force: true }), params(RUN_ID))).status).toBe(400);
    expect(forwarded).toEqual([]);
    expect((await stopRun(post('/stop'), params(RUN_ID))).status).toBe(200);
    expect(forwarded).toEqual([
      {
        url: `http://rest/v1/tenants/acme/pact-verifier/runs/${RUN_ID}/stop`,
        method: 'POST',
        body: undefined,
      },
    ]);
  });

  it('re-runs one interaction and passes REST’s 409 through', async () => {
    restAnswer = () =>
      NextResponse.json({ success: false, error: 'The run is still going.' }, { status: 409 });
    const answer = await rerunRun(
      post('/rerun', { pact_version_sha: SHA, case_id: 'pact:0' }),
      params(RUN_ID),
    );
    expect(answer.status).toBe(409);
    expect(forwarded).toEqual([
      {
        url: `http://rest/v1/tenants/acme/pact-verifier/runs/${RUN_ID}/rerun`,
        method: 'POST',
        body: { pact_version_sha: SHA, case_id: 'pact:0' },
      },
    ]);
    forwarded.length = 0;
    expect(
      (
        await rerunRun(
          post('/rerun', { pact_version_sha: SHA, case_id: 'pact:0', publish: true }),
          params(RUN_ID),
        )
      ).status,
    ).toBe(400);
    expect(forwarded).toEqual([]);
  });
});

describe('the upload route', () => {
  const BODY = {
    provider: 'billing-service',
    consumer: 'orders-ui',
    pact_version_sha: SHA,
    provider_version: '2.7.0',
    format: 'auto',
    report: '<testsuite name="Dredd Tests"><testcase name="GET /x"/></testsuite>',
    content_type: 'application/xml',
  };
  let sent: Array<{ url: string; init: RequestInit }>;

  beforeEach(() => {
    sent = [];
  });

  function rest(status: number, body: unknown) {
    global.fetch = jest.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      sent.push({ url: String(url), init: init ?? {} });
      return new Response(JSON.stringify(body), { status });
    }) as unknown as typeof fetch;
  }

  it('sends the report itself with its media type', async () => {
    rest(201, { success: true, ingestion: { format: 'dredd', interactions: 1, notices: [] } });
    const answer = await upload(post('/upload', BODY));
    expect(answer.status).toBe(200);
    expect((await answer.json()).ingestion.format).toBe('dredd');
    expect(sent).toHaveLength(1);
    expect(sent[0].url).toBe(
      `http://rest/v1/tenants/acme/pact-broker/pacts/provider/billing-service/consumer/orders-ui/pact-version/${SHA}/external-verification-results?providerApplicationVersion=2.7.0`,
    );
    expect(sent[0].init.method).toBe('POST');
    expect(sent[0].init.body).toBe(BODY.report);
    expect(sent[0].init.headers).toMatchObject({
      Authorization: 'Bearer session',
      'Content-Type': 'application/xml',
    });
  });

  it('passes an unreadable report’s refusal through with its reason and pointer', async () => {
    rest(422, {
      detail: {
        code: 'pact-verification-invalid',
        message: '/format: format is dredd but the report is JSON',
        pointer: '/format',
      },
    });
    const answer = await upload(
      post('/upload', { ...BODY, format: 'dredd', report: '{}', content_type: 'application/json' }),
    );
    expect(answer.status).toBe(422);
    const body = await answer.json();
    expect(body.pointer).toBe('/format');
    expect(body.error).toContain('format is dredd');
  });

  it('refuses a field the dialog does not send without calling REST', async () => {
    rest(201, {});
    const answer = await upload(post('/upload', { ...BODY, tenant: 'other' }));
    expect(answer.status).toBe(400);
    expect(sent).toEqual([]);
  });

  it('is a 503 when apiome-rest cannot be reached', async () => {
    global.fetch = jest.fn(async () => {
      throw new Error('ECONNREFUSED');
    }) as unknown as typeof fetch;
    const answer = await upload(post('/upload', BODY));
    expect(answer.status).toBe(503);
    expect((await answer.json()).error).toContain('Pact Broker is unavailable');
  });
});
