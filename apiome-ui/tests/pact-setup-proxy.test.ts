/**
 * @jest-environment node
 */
/**
 * The BFF of **Set up contracts** — PFX-8.20 (#7317): `/api/pact/setup` (read, save),
 * `/api/pact/setup/github/secrets` and `/api/pact/setup/github/pull-requests`.
 *
 * * an unknown parameter or field is a 400 naming it — REST is not called;
 * * a checked call is forwarded as the signed-in user to the workspace's `pact-setup` path;
 * * the broker address of the secrets is the workspace's own, added here, never the browser's;
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
jest.mock('@lib/pact-badges', () => ({ PUBLIC_REST_BASE_URL: 'https://api.apiome.dev/v1' }));

import { GET as readSetup, PUT as saveSetup } from '../src/app/api/pact/setup/route';
import { POST as writeSecrets } from '../src/app/api/pact/setup/github/secrets/route';
import { POST as openPullRequests } from '../src/app/api/pact/setup/github/pull-requests/route';

const REPO = '22222222-2222-4222-8222-222222222222';
const BASE = 'http://rest/v1/tenants/acme/pact-setup';
const KEY = 'apk_live_0123456789abcdef';

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

describe('reading and saving', () => {
  it('reads the set-up and takes no parameter', async () => {
    expect((await readSetup(await request('/api/pact/setup', undefined, 'GET'))).status).toBe(200);
    expect(forwarded).toEqual([{ url: BASE, method: 'GET', body: undefined }]);
    const refused = await readSetup(await request('/api/pact/setup?tenant=other', undefined, 'GET'));
    expect(refused.status).toBe(400);
    expect((await refused.json()).error).toContain('tenant');
    expect(forwarded).toHaveLength(1);
  });

  it('saves a checked change and refuses an unknown field or section', async () => {
    expect((await saveSetup(await request('/api/pact/setup', { mark: { gates: true } }, 'PUT'))).status).toBe(200);
    expect(forwarded).toEqual([{ url: BASE, method: 'PUT', body: { mark: { gates: true } } }]);
    for (const body of [{ done: true }, { mark: { billing: true } }, {}]) {
      const refused = await saveSetup(await request('/api/pact/setup', body, 'PUT'));
      expect(refused.status).toBe(400);
    }
    expect(forwarded).toHaveLength(1);
  });

  it('keeps REST’s refusal', async () => {
    restAnswer = () => NextResponse.json({ success: false, error: 'Permission denied' }, { status: 403 });
    expect((await saveSetup(await request('/api/pact/setup', { mark: { gates: true } }, 'PUT'))).status).toBe(403);
  });
});

describe('the GitHub actions', () => {
  it('adds the workspace’s own broker address to the secrets and passes the key through', async () => {
    const response = await writeSecrets(await request('/api/pact/setup/github/secrets', { repository_ids: [REPO], token: KEY }));
    expect(response.status).toBe(200);
    expect(forwarded).toEqual([
      {
        url: `${BASE}/github/secrets`,
        method: 'POST',
        body: { repository_ids: [REPO], token: KEY, broker_base_url: 'https://api.apiome.dev/v1/tenants/acme/pact-broker' },
      },
    ]);
  });

  it('refuses an address from the browser, a bad id and a missing key before calling REST', async () => {
    for (const body of [
      { repository_ids: [REPO], token: KEY, broker_base_url: 'https://evil.example' },
      { repository_ids: ['nope'], token: KEY },
      { repository_ids: [REPO] },
    ]) {
      expect((await writeSecrets(await request('/api/pact/setup/github/secrets', body))).status).toBe(400);
    }
    expect(forwarded).toHaveLength(0);
  });

  it('forwards a pull-request request with its defaults, and a preview as a preview', async () => {
    const body = { repositories: [{ repository_id: REPO, pacticipant: 'Billing Service' }], environment: 'production' };
    expect((await openPullRequests(await request('/api/pact/setup/github/pull-requests', body))).status).toBe(200);
    expect((await openPullRequests(await request('/api/pact/setup/github/pull-requests', { ...body, preview: true }))).status).toBe(200);
    expect(forwarded.map((call) => [call.url, (call.body as { preview: boolean }).preview])).toEqual([
      [`${BASE}/github/pull-requests`, false],
      [`${BASE}/github/pull-requests`, true],
    ]);
    expect(forwarded[0].body).toMatchObject({ can_i_deploy: true, record_deployment: true });
  });

  it('refuses a pull-request request with no step or an unknown field', async () => {
    const body = { repositories: [{ repository_id: REPO, pacticipant: 'Billing Service' }], environment: 'production' };
    for (const bad of [{ ...body, can_i_deploy: false, record_deployment: false }, { ...body, branch: 'x' }, { environment: 'production' }]) {
      expect((await openPullRequests(await request('/api/pact/setup/github/pull-requests', bad))).status).toBe(400);
    }
    expect(forwarded).toHaveLength(0);
  });
});
