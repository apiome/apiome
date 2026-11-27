/**
 * @jest-environment node
 */
/**
 * The provider's spec for **Write interactions** — PFX-8.5 (#7302):
 *
 * * the OpenAPI outline: operations, `$ref` / `allOf` resolved, examples from the spec or generated
 *   (and marked), typed fields with Pact paths, cycles stopped;
 * * the read: pacticipant → linked project → latest revision → document and mock scenarios, plus
 *   the catalogue's states — every read in the caller's own workspace, a refused pacticipant read
 *   keeps REST's status (RBAC is REST's), a part that cannot be read is named, never dropped;
 * * the proxy: exactly `provider`, else a 400 without calling REST; a 403 passes through.
 */

import { jest } from '@jest/globals';
import {
  latestRevision,
  loadProviderSpec,
  outlineOpenApi,
  pathFits,
  pickSpecQuery,
  stateSuggestions,
  type FetchJson,
  type JsonAnswer,
} from '../lib/pact-provider-spec';

const DOCUMENT = {
  openapi: '3.2.0',
  paths: {
    '/invoices/{id}': {
      get: {
        summary: 'Get an invoice',
        responses: {
          '200': { $ref: '#/components/responses/Invoice' },
          '404': { description: 'Not found' },
        },
      },
    },
    '/invoices': {
      post: {
        operationId: 'createInvoice',
        responses: {
          '201': {
            content: {
              'application/json': {
                examples: { one: { value: { id: 7 } } },
                schema: { $ref: '#/components/schemas/Invoice' },
              },
            },
          },
        },
      },
    },
    '/nodes': {
      get: { responses: { '200': { content: { 'application/json': { schema: { $ref: '#/components/schemas/Node' } } } } } },
    },
  },
  components: {
    responses: {
      Invoice: { content: { 'text/plain': { schema: { type: 'string' } }, 'application/json': { schema: { $ref: '#/components/schemas/Invoice' } } } },
    },
    schemas: {
      Money: { type: 'object', properties: { amount: { type: 'integer' }, currency: { type: 'string', pattern: '^[A-Z]{3}$' } } },
      Invoice: {
        allOf: [
          { $ref: '#/components/schemas/Money' },
          {
            type: 'object',
            properties: {
              id: { type: 'integer' },
              status: { type: 'string', enum: ['open', 'paid'] },
              issued: { type: 'string', format: 'date' },
              'line items': { type: 'array', items: { type: 'object', properties: { sku: { type: 'string' } } } },
            },
          },
        ],
      },
      Node: { type: 'object', properties: { name: { type: 'string' }, child: { $ref: '#/components/schemas/Node' } } },
    },
  },
};

describe('outlineOpenApi', () => {
  const { operations, leftOut } = outlineOpenApi(DOCUMENT);

  it('lists each operation with its responses', () => {
    expect(leftOut).toBe(0);
    expect(operations.map((op) => `${op.method} ${op.path} ${op.summary}`)).toEqual([
      'GET /invoices/{id} Get an invoice',
      'POST /invoices createInvoice',
      'GET /nodes null',
    ]);
    expect(operations[0].responses.map((r) => [r.status, r.contentType, r.exampleSource])).toEqual([
      ['200', 'application/json', 'schema'],
      ['404', null, 'none'],
    ]);
  });

  it('resolves $ref and allOf into typed fields with Pact paths', () => {
    expect(operations[0].responses[0].fields).toEqual([
      { path: '$.amount', type: 'integer' },
      { path: '$.currency', type: 'string', pattern: '^[A-Z]{3}$' },
      { path: '$.id', type: 'integer' },
      { path: '$.status', type: 'string', enum: ['open', 'paid'] },
      { path: '$.issued', type: 'string', format: 'date' },
      { path: "$['line items']", type: 'array' },
      { path: "$['line items'][*].sku", type: 'string' },
    ]);
  });

  it('takes the spec’s example first, and generates one from the schema otherwise', () => {
    expect(operations[1].responses[0]).toMatchObject({ example: { id: 7 }, exampleSource: 'spec' });
    expect(operations[0].responses[0].example).toEqual({ id: 1, status: 'open', issued: '2026-01-31', 'line items': [{ sku: 'string' }], amount: 1, currency: 'string' });
  });

  it('stops at a recursive schema', () => {
    expect(operations[2].responses[0].fields).toEqual([{ path: '$.name', type: 'string' }]);
  });

  it('reads nothing from a document without paths', () => {
    expect(outlineOpenApi(null)).toEqual({ operations: [], leftOut: 0 });
    expect(outlineOpenApi({ asyncapi: '3.0.0' })).toEqual({ operations: [], leftOut: 0 });
  });
});

describe('pathFits', () => {
  it.each([
    ['/invoices/{id}', '/invoices/42', true],
    ['/invoices/{id}', '/invoices/42/', true],
    ['/invoices/{id}', '/invoices', false],
    ['/files/{name}.json', '/files/a.json', true],
    ['/files/{name}.json', '/files/a.xml', false],
    ['/a.b', '/axb', false],
  ])('%s fits %s: %s', (template, path, fits) => {
    expect(pathFits(template, path)).toBe(fits);
  });
});

describe('suggestions and revisions', () => {
  it('lists catalogue states first, then mock scenarios not already named', () => {
    expect(
      stateSuggestions(
        [{ name: 'an invoice exists', parameters: [{ name: 'id', required: true }, { name: 'currency' }], description: 'Seeds one invoice' }],
        { scenarios: { 'an invoice exists': {}, 'billing is down': { description: 'Every call answers 503' } } },
      ),
    ).toEqual([
      { name: 'an invoice exists', source: 'catalogue', parameters: [{ name: 'id', required: true }, { name: 'currency', required: false }], description: 'Seeds one invoice' },
      { name: 'billing is down', source: 'mock', parameters: [], description: 'Every call answers 503' },
    ]);
  });

  it('takes the most recently created revision', () => {
    expect(
      latestRevision([
        { id: 'v1', version_id: '1.0.0', created_at: '2026-01-01T00:00:00Z' },
        { id: 'v2', version_id: '2.7.0', created_at: '2026-03-01T00:00:00Z' },
        { id: 'v0', created_at: '2025-01-01T00:00:00Z' },
      ]),
    ).toEqual({ id: 'v2', label: '2.7.0' });
    expect(latestRevision([])).toBeNull();
    expect(latestRevision({})).toBeNull();
  });
});

const URLS = {
  tenant: (path: string) => `http://rest/v1/tenants/acme/${path}`,
  versions: (path: string) => `http://rest/v1/versions/acme/${path}`,
};

/** REST answers by URL; anything unlisted is a 404. */
function rest(table: Record<string, JsonAnswer | null>): { fetchJson: FetchJson; urls: string[] } {
  const urls: string[] = [];
  return {
    urls,
    fetchJson: async (url) => {
      urls.push(url);
      return url in table ? table[url] : { status: 404, body: { detail: 'Not found' } };
    },
  };
}

const LINKED = {
  'http://rest/v1/tenants/acme/pacticipants/billing-service': { status: 200, body: { slug: 'billing-service', name: 'Billing Service', project_id: 'p-1' } },
  'http://rest/v1/tenants/acme/pact-verifier/providers/billing-service/provider-states': { status: 200, body: [{ name: 'an invoice exists', parameters: [{ name: 'id', required: true }] }] },
  'http://rest/v1/versions/acme/p-1': { status: 200, body: [{ id: 'v-2', version_id: '2.7.0', created_at: '2026-03-01T00:00:00Z' }] },
  'http://rest/v1/versions/acme/p-1/v-2/document': { status: 200, body: DOCUMENT },
  'http://rest/v1/versions/acme/p-1/v-2/mock/scenarios': { status: 200, body: { scenarios: { 'billing is down': {} } } },
};

describe('loadProviderSpec', () => {
  it('reads the linked project’s latest revision, its mock scenarios and the catalogue — in the caller’s workspace only', async () => {
    const { fetchJson, urls } = rest(LINKED);
    const spec = await loadProviderSpec('Billing Service', URLS, fetchJson);
    if ('error' in spec) throw new Error(spec.error);
    expect(spec.revision).toEqual({ projectId: 'p-1', versionId: 'v-2', label: '2.7.0' });
    expect(spec.operations).toHaveLength(3);
    expect(spec.states.map((s) => `${s.source}:${s.name}`)).toEqual(['catalogue:an invoice exists', 'mock:billing is down']);
    expect(spec.problems).toEqual([]);
    expect(urls.every((url) => url.startsWith('http://rest/v1/tenants/acme/') || url.startsWith('http://rest/v1/versions/acme/'))).toBe(true);
  });

  it('keeps REST’s refusal of the pacticipant read (RBAC is REST’s)', async () => {
    const { fetchJson, urls } = rest({ 'http://rest/v1/tenants/acme/pacticipants/billing-service': { status: 403, body: { detail: 'Missing permission pacts:view' } } });
    expect(await loadProviderSpec('Billing Service', URLS, fetchJson)).toEqual({ status: 403, error: 'Missing permission pacts:view' });
    expect(urls.some((url) => url.includes('/versions/'))).toBe(false);
  });

  it('is unavailable when REST cannot be reached', async () => {
    const { fetchJson } = rest({ 'http://rest/v1/tenants/acme/pacticipants/billing-service': null });
    expect(await loadProviderSpec('Billing Service', URLS, fetchJson)).toMatchObject({ status: 503 });
  });

  it('names a provider that is not a pacticipant yet, and still answers', async () => {
    const { fetchJson } = rest({});
    const spec = await loadProviderSpec('Billing Service', URLS, fetchJson);
    expect(spec).toEqual({
      provider: 'Billing Service',
      revision: null,
      operations: [],
      states: [],
      problems: ['Billing Service is not a pacticipant yet, so there is no spec to check paths against. Interactions are written and published all the same.'],
    });
  });

  it('names an unlinked pacticipant, a project with no revision, and each part it could not read', async () => {
    const unlinked = rest({ ...LINKED, 'http://rest/v1/tenants/acme/pacticipants/billing-service': { status: 200, body: { project_id: null } } });
    const a = await loadProviderSpec('Billing Service', URLS, unlinked.fetchJson);
    expect('problems' in a && a.problems).toEqual(['Billing Service is not linked to a project, so paths are not checked against a spec. Link it on its pacticipant page.']);

    const empty = rest({ ...LINKED, 'http://rest/v1/versions/acme/p-1': { status: 200, body: [] } });
    const b = await loadProviderSpec('Billing Service', URLS, empty.fetchJson);
    expect('problems' in b && b.problems).toEqual(['Billing Service’s project has no revision yet, so there is no spec to check paths against.']);

    const parts = rest({
      ...LINKED,
      'http://rest/v1/versions/acme/p-1/v-2/document': { status: 403, body: { detail: 'Missing permission versions:view' } },
      'http://rest/v1/versions/acme/p-1/v-2/mock/scenarios': null,
      'http://rest/v1/tenants/acme/pact-verifier/providers/billing-service/provider-states': { status: 500, body: { error: 'boom' } },
    });
    const c = await loadProviderSpec('Billing Service', URLS, parts.fetchJson);
    if ('error' in c) throw new Error(c.error);
    expect(c.operations).toEqual([]);
    expect(c.problems).toEqual([
      'The spec of revision 2.7.0 could not be read: Missing permission versions:view.',
      'The mock’s scenarios could not be read, so none are suggested as provider states: apiome-rest not reachable.',
      'The provider-state catalogue could not be read: boom.',
    ]);
  });
});

describe('pickSpecQuery', () => {
  it.each([
    ['provider=Billing%20Service', { ok: true, provider: 'Billing Service' }],
    ['', { ok: false, error: 'provider is required.' }],
    ['provider=a&provider=b', { ok: false, error: 'The provider parameter is given more than once.' }],
    ['provider=a&tenant=other', { ok: false, error: 'Unsupported parameter tenant: the spec read takes provider only.' }],
    [`provider=${'x'.repeat(256)}`, { ok: false, error: 'provider is longer than 255 characters.' }],
    ['provider=a%0Ab', { ok: false, error: 'provider contains a control character.' }],
  ])('%s', (query, expected) => {
    expect(pickSpecQuery(new URLSearchParams(query))).toEqual(expected);
  });
});

// --- the route -------------------------------------------------------------------------------------

const restCalls: Array<{ url: string; auth: string | undefined }> = [];
let restTable: Record<string, { status: number; body: unknown }> = {};

jest.mock('@lib/connectors-proxy', () => ({
  resolveConnectorTenant: async () => ({ user: { user_id: 'u-1' }, slug: 'acme' }),
}));
jest.mock('@lib/rest-auth', () => ({
  createRestAuthHeaders: () => ({ Authorization: 'Bearer session-u-1' }),
  REST_API_BASE_URL: 'http://rest/v1',
}));
jest.mock('@lib/rest-paged-list', () => ({
  fetchAllPages: async (url: string, init: RequestInit) => {
    restCalls.push({ url, auth: (init.headers as Record<string, string>).Authorization });
    const answer = restTable[url] ?? { status: 404, body: { detail: 'Not found' } };
    return new Response(JSON.stringify(answer.body), { status: answer.status });
  },
}));

import { GET } from '../src/app/api/pact/publish/provider-spec/route';

function get(query: string) {
  return GET({ nextUrl: new URL(`http://x/api/pact/publish/provider-spec?${query}`) } as never);
}

describe('/api/pact/publish/provider-spec', () => {
  beforeEach(() => {
    restCalls.length = 0;
    restTable = Object.fromEntries(Object.entries(LINKED).map(([url, answer]) => [url, answer as { status: number; body: unknown }]));
  });

  it('reads the spec as the signed-in user, in their workspace', async () => {
    const response = await get('provider=Billing%20Service');
    expect(response.status).toBe(200);
    const body = await response.json();
    expect(body.revision).toEqual({ projectId: 'p-1', versionId: 'v-2', label: '2.7.0' });
    expect(restCalls.length).toBe(5);
    expect(restCalls.every((call) => call.auth === 'Bearer session-u-1')).toBe(true);
    expect(restCalls.every((call) => /^http:\/\/rest\/v1\/(tenants|versions)\/acme\//.test(call.url))).toBe(true);
  });

  it('passes REST’s 403 through', async () => {
    restTable['http://rest/v1/tenants/acme/pacticipants/billing-service'] = { status: 403, body: { detail: 'Missing permission pacts:view' } };
    const response = await get('provider=Billing%20Service');
    expect(response.status).toBe(403);
    expect(await response.json()).toEqual({ success: false, error: 'Missing permission pacts:view' });
  });

  it.each(['', 'provider=a&slug=other', 'provider=a&provider=b'])('refuses %j without calling REST', async (query) => {
    const response = await get(query);
    expect(response.status).toBe(400);
    expect(restCalls).toEqual([]);
  });
});
