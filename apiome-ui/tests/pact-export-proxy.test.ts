/**
 * @jest-environment node
 */
/**
 * The Export page's BFF — PFX-8.18 (#7315): `/api/pact/export/consumer-pact`, `/postman`,
 * `/pact-file` and `/provider-pacts`.
 *
 * * a bad parameter or field is a 400 naming it, and REST is not called;
 * * a checked call goes to the signed-in user's workspace, as that user (tenant isolation is the
 *   resolved tenant's: nothing in the request can name another);
 * * REST's refusal keeps its status, code, findings and notices (a 403 without `pacts:view` stays a 403);
 * * a pact file is returned exactly as stored; the zip carries each consumer's pact and a README
 *   naming every consumer left out and why.
 */

import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

jest.mock('@lib/connectors-proxy', () => ({
  resolveConnectorTenant: async () => ({ user: { user_id: 'u-1' }, slug: 'acme' }),
  tenantUrl: (slug: string, p: string) => `http://rest/v1/tenants/${slug}/${p}`,
  forwardConnectorRequest: jest.fn(),
}));
jest.mock('@lib/rest-auth', () => ({
  createRestAuthHeaders: () => ({ Authorization: 'Bearer session' }),
  REST_API_BASE_URL: 'http://rest/v1',
}));

import { GET as consumerPact } from '../src/app/api/pact/export/consumer-pact/route';
import { POST as postman } from '../src/app/api/pact/export/postman/route';
import { GET as pactFile } from '../src/app/api/pact/export/pact-file/route';
import { GET as providerPacts } from '../src/app/api/pact/export/provider-pacts/route';
import { GET as providerTests } from '../src/app/api/pact/export/provider-tests/route';
import { providerPactConsumers, refusalBody, zipReadme } from '../lib/pact-export-proxy';

type Sent = { url: string; method: string; body?: unknown; auth?: string };
let sent: Sent[];
let answer: (url: string) => { status: number; body: unknown };

beforeEach(() => {
  sent = [];
  answer = () => ({ status: 200, body: {} });
  global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const headers = (init?.headers ?? {}) as Record<string, string>;
    sent.push({ url, method: init?.method ?? 'GET', body: init?.body ? JSON.parse(String(init.body)) : undefined, auth: headers.Authorization });
    const reply = answer(url);
    return new Response(JSON.stringify(reply.body), { status: reply.status, headers: { 'Content-Type': 'application/json' } });
  }) as unknown as typeof fetch;
});

async function request(url: string, body?: unknown, method = body === undefined ? 'GET' : 'POST') {
  const { NextRequest } = await import('next/server');
  return new NextRequest(`http://localhost${url}`, { method, ...(body === undefined ? {} : { body: typeof body === 'string' ? body : JSON.stringify(body) }) });
}

describe('a pact from a project', () => {
  it('forwards the checked query as the signed-in user', async () => {
    answer = () => ({ status: 200, body: { pact: { interactions: [] }, operations: [] } });
    const response = await consumerPact(await request('/api/pact/export/consumer-pact?project=billing-api&consumer=orders-ui&revision=4'));
    expect(response.status).toBe(200);
    expect(sent).toEqual([
      { url: 'http://rest/v1/tenants/acme/projects/billing-api/consumers/orders-ui/pact?revision=4', method: 'GET', body: undefined, auth: 'Bearer session' },
    ]);
  });

  it('refuses a bad query without calling REST', async () => {
    const response = await consumerPact(await request('/api/pact/export/consumer-pact?project=p&consumer=c&tenant=other'));
    expect(response.status).toBe(400);
    expect((await response.json()).error).toContain('Unsupported parameter tenant');
    expect(sent).toEqual([]);
  });

  it('keeps REST’s code and findings on a refusal', async () => {
    answer = () => ({
      status: 422,
      body: { detail: { code: 'consumer-pact-export-empty', message: 'no interaction', findings: [{ outcome: 'omitted', reason: 'status-default', message: 'default' }] } },
    });
    const response = await consumerPact(await request('/api/pact/export/consumer-pact?project=p&consumer=c'));
    expect(response.status).toBe(422);
    expect(await response.json()).toEqual({
      success: false,
      error: 'no interaction',
      code: 'consumer-pact-export-empty',
      findings: [{ outcome: 'omitted', reason: 'status-default', message: 'default' }],
    });
  });

  it('keeps a 403 a 403', async () => {
    answer = () => ({ status: 403, body: { detail: 'Permission denied: pacts:view' } });
    const response = await consumerPact(await request('/api/pact/export/consumer-pact?project=p&consumer=c'));
    expect(response.status).toBe(403);
    expect((await response.json()).error).toBe('Permission denied: pacts:view');
  });
});

describe('a Postman collection', () => {
  it('forwards the checked body unchanged', async () => {
    const body = { provider: 'billing', allConsumers: true, stateSetup: true, tests: true };
    answer = () => ({ status: 200, body: { collection: {}, counts: {}, notices: [] } });
    expect((await postman(await request('/api/pact/export/postman', body))).status).toBe(200);
    expect(sent).toEqual([{ url: 'http://rest/v1/tenants/acme/pact-postman-collections', method: 'POST', body, auth: 'Bearer session' }]);
  });

  it('refuses an unknown field or bad JSON without calling REST', async () => {
    expect((await postman(await request('/api/pact/export/postman', { provider: 'p', tenant: 'other' }))).status).toBe(400);
    expect((await postman(await request('/api/pact/export/postman', 'not json'))).status).toBe(400);
    expect(sent).toEqual([]);
  });

  it('keeps the notices of a pact with no HTTP interaction', async () => {
    const notices = [{ code: 'pact-postman-message-left-out', outcome: 'left-out', pointer: '/messages/0', message: 'a message' }];
    answer = () => ({ status: 422, body: { detail: { code: 'pact-postman-no-http-interactions', message: 'no HTTP', notices } } });
    const response = await postman(await request('/api/pact/export/postman', { provider: 'p', consumer: 'c' }));
    expect(response.status).toBe(422);
    expect(await response.json()).toMatchObject({ code: 'pact-postman-no-http-interactions', notices });
  });

  it('reads a REST that cannot be reached as a 503', async () => {
    global.fetch = jest.fn(async () => {
      throw new Error('ECONNREFUSED');
    }) as unknown as typeof fetch;
    expect((await postman(await request('/api/pact/export/postman', { provider: 'p', consumer: 'c' }))).status).toBe(503);
  });
});

describe('a pact file', () => {
  it('returns the stored pact without the broker’s decoration', async () => {
    answer = () => ({ status: 200, body: { consumer: { name: 'Orders UI' }, interactions: [], createdAt: 'x', _links: { self: {} } } });
    const response = await pactFile(await request('/api/pact/export/pact-file?provider=billing&consumer=orders-ui&branch=main'));
    expect(sent[0].url).toBe('http://rest/v1/tenants/acme/pact-broker/pacts/provider/billing/consumer/orders-ui/branch/main/latest');
    expect(await response.json()).toEqual({ pact: { consumer: { name: 'Orders UI' }, interactions: [] }, fileName: 'orders-ui-billing.json' });
  });

  it('keeps REST’s 404 for a pair without such a pact', async () => {
    answer = () => ({ status: 404, body: { detail: { code: 'pact-not-found', message: 'no pact' } } });
    const response = await pactFile(await request('/api/pact/export/pact-file?provider=billing&consumer=orders-ui'));
    expect(response.status).toBe(404);
    expect(await response.json()).toMatchObject({ code: 'pact-not-found', error: 'no pact' });
  });

  it('refuses two choices without calling REST', async () => {
    expect((await pactFile(await request('/api/pact/export/pact-file?provider=b&consumer=c&tag=a&version=1'))).status).toBe(400);
    expect(sent).toEqual([]);
  });
});

describe('every pact for a provider', () => {
  const list = { _links: { 'pb:pacts': [{ name: 'Admin' }, { name: 'Orders UI' }] } };

  it('zips each consumer’s pact and names the ones left out', async () => {
    answer = (url) => {
      if (url.endsWith('/pacts/provider/billing/latest')) return { status: 200, body: list };
      if (url.includes('/consumer/Admin/')) return { status: 404, body: { detail: { code: 'pact-not-found', message: "no pact from branch 'main'" } } };
      return { status: 200, body: { consumer: { name: 'Orders UI' }, interactions: [], _links: {} } };
    };
    const response = await providerPacts(await request('/api/pact/export/provider-pacts?provider=billing&branch=main'));
    expect(response.status).toBe(200);
    expect(response.headers.get('Content-Type')).toBe('application/zip');
    expect(response.headers.get('Content-Disposition')).toBe('attachment; filename="billing-pacts.zip"');
    expect(sent.map((call) => call.url)).toEqual([
      'http://rest/v1/tenants/acme/pact-broker/pacts/provider/billing/latest',
      'http://rest/v1/tenants/acme/pact-broker/pacts/provider/billing/consumer/Admin/branch/main/latest',
      'http://rest/v1/tenants/acme/pact-broker/pacts/provider/billing/consumer/Orders%20UI/branch/main/latest',
    ]);
    const bytes = new Uint8Array(await response.arrayBuffer());
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'pexp-proxy-'));
    const file = path.join(dir, 'pacts.zip');
    fs.writeFileSync(file, bytes);
    try {
      expect(JSON.parse(execFileSync('unzip', ['-p', file, 'orders-ui-billing.json']).toString())).toEqual({ consumer: { name: 'Orders UI' }, interactions: [] });
      const readme = execFileSync('unzip', ['-p', file, 'README.txt']).toString();
      expect(readme).toContain("Admin: no pact from branch 'main'");
      expect(readme).toContain('latest on branch main');
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error;
    } finally {
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });

  it('reads the tagged list for a tag', async () => {
    answer = (url) => (url.endsWith('/latest/prod') && url.includes('/provider/billing/latest') ? { status: 200, body: { _links: { 'pb:pacts': [] } } } : { status: 200, body: {} });
    const response = await providerPacts(await request('/api/pact/export/provider-pacts?provider=billing&tag=prod'));
    expect(sent[0].url).toBe('http://rest/v1/tenants/acme/pact-broker/pacts/provider/billing/latest/prod');
    expect(response.status).toBe(404);
    expect((await response.json()).error).toContain('No consumer has published a pact (latest with tag prod) for billing.');
  });

  it('keeps REST’s refusal of the list', async () => {
    answer = () => ({ status: 403, body: { detail: 'Permission denied' } });
    expect((await providerPacts(await request('/api/pact/export/provider-pacts?provider=billing'))).status).toBe(403);
  });

  it('refuses a version without calling REST', async () => {
    expect((await providerPacts(await request('/api/pact/export/provider-pacts?provider=billing&version=1'))).status).toBe(400);
    expect(sent).toEqual([]);
  });
});

describe('provider test scaffolding', () => {
  it('forwards the checked query as the signed-in user', async () => {
    answer = () => ({ status: 200, body: { content: '', file_name: 'x.ts' } });
    expect((await providerTests(await request('/api/pact/export/provider-tests?provider=Billing%20Service&language=go'))).status).toBe(200);
    expect(sent).toEqual([
      { url: 'http://rest/v1/tenants/acme/pact-provider-tests/Billing%20Service?language=go', method: 'GET', body: undefined, auth: 'Bearer session' },
    ]);
  });

  it('refuses an unknown language without calling REST', async () => {
    const response = await providerTests(await request('/api/pact/export/provider-tests?provider=b&language=cobol'));
    expect(response.status).toBe(400);
    expect(sent).toEqual([]);
  });

  it('keeps REST’s 404 and 403', async () => {
    answer = () => ({ status: 404, body: { detail: { code: 'pacticipant-not-found', message: 'no such provider' } } });
    const missing = await providerTests(await request('/api/pact/export/provider-tests?provider=b&language=go'));
    expect(missing.status).toBe(404);
    expect(await missing.json()).toMatchObject({ code: 'pacticipant-not-found' });
    answer = () => ({ status: 403, body: { detail: 'Permission denied' } });
    expect((await providerTests(await request('/api/pact/export/provider-tests?provider=b&language=go'))).status).toBe(403);
  });
});

describe('the helpers', () => {
  it('reads a refusal of any shape', () => {
    expect(refusalBody({ detail: 'nope' }, 403)).toEqual({ success: false, error: 'nope' });
    expect(refusalBody({}, 500)).toEqual({ success: false, error: 'The export was refused (HTTP 500).' });
    expect(refusalBody({ detail: { code: 'x' } }, 422)).toEqual({ success: false, error: 'HTTP 422', code: 'x' });
  });

  it('reads the consumers of the provider-pacts list', () => {
    expect(providerPactConsumers({ _links: { 'pb:pacts': [{ name: 'A' }, { href: 'x' }, { name: '' }] } })).toEqual(['A']);
    expect(providerPactConsumers(null)).toEqual([]);
  });

  it('writes a README with nothing left out', () => {
    expect(zipReadme('billing', 'latest', ['a.json'], [])).toContain('Left out (0):\n  none');
  });
});
