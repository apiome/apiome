/**
 * @jest-environment node
 */
/**
 * The **Publish a consumer pact** page — PFX-8.3 (#7300): the model (`lib/pact-publish-page.ts`),
 * the several-pacts form of `/api/pact/publish`, and the two new proxies (`/api/pact/publish/check`,
 * `/api/pact/publish/consumer-contract`). Each failure path has its own test.
 */

import { jest } from '@jest/globals';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { NextRequest, NextResponse } from 'next/server';

const forwarded: Array<{ url: string; method: string; body?: unknown }> = [];

jest.mock('@lib/connectors-proxy', () => ({
  resolveConnectorTenant: async () => ({ user: { user_id: 'u-1' }, slug: 'acme' }),
  tenantUrl: (slug: string, path: string) => `http://rest/v1/tenants/${slug}/${path}`,
  forwardConnectorRequest: async (url: string, init: { method: string; body?: unknown }) => {
    forwarded.push({ url, method: init.method, body: init.body });
    return NextResponse.json({ ok: true });
  },
}));
jest.mock('@lib/rest-auth', () => ({
  createRestAuthHeaders: () => ({ Authorization: 'Bearer session' }),
  REST_API_BASE_URL: 'http://rest/v1',
}));

import { pickPublishBody } from '../lib/pact-publish';
import {
  EMPTY_DERIVE,
  EMPTY_WHOSE,
  MERGE_REFUSED,
  PUBLISH_FLAG_FIELDS,
  annotateRows,
  checkSentence,
  classifyCheck,
  effectiveTags,
  pacticipantKey,
  pactVersionSha,
  pickCheckQuery,
  pickDeriveBody,
  publishBatches,
  publishCommandAction,
  publishRoute,
  publishableRows,
  publishedSentence,
  readDeriveOutcome,
  readPactFile,
  readPublishOutcome,
  readPublishPrefill,
  refusedContractIndex,
  samePactContent,
  specLabel,
  validateDerive,
  validateWhose,
  type WhoseVersion,
} from '../lib/pact-publish-page';
import { pactCommandSurfaces, unsupportedLines } from '../lib/pact-commands';
import { GET as CHECK } from '../src/app/api/pact/publish/check/route';
import { POST as DERIVE } from '../src/app/api/pact/publish/consumer-contract/route';

/** A small valid pact. */
function pact(consumer = 'Orders UI', provider = 'Billing Service', extra: Record<string, unknown> = {}) {
  return JSON.stringify({
    consumer: { name: consumer },
    provider: { name: provider },
    interactions: [
      { description: 'get invoice', request: { method: 'GET', path: '/invoices/1' }, response: { status: 200 } },
      { description: 'an event', type: 'Asynchronous/Messages', contents: {} },
    ],
    metadata: { pactSpecification: { version: '3.0.0' } },
    ...extra,
  });
}

const WHOSE: WhoseVersion = { ...EMPTY_WHOSE, version: '3.4.0', branch: 'feature/credit-notes', tags: 'dev' };

beforeEach(() => {
  forwarded.length = 0;
});

describe('reading a file', () => {
  it('reads the pair, specification, count and kinds', () => {
    const row = readPactFile('a', 'orders.json', pact());
    expect(row).toMatchObject({ consumer: 'Orders UI', provider: 'Billing Service', specVersion: '3.0.0', interactions: 2, problem: null });
    expect(row.kinds).toEqual(['HTTP', 'Message']);
    expect(specLabel(row.specVersion)).toBe('Pact v3');
    expect(specLabel(null)).toBe('Unstated');
  });

  it('counts messages and tells GraphQL apart', () => {
    const graphql = readPactFile(
      'g',
      'g.json',
      JSON.stringify({
        consumer: { name: 'A' },
        provider: { name: 'B' },
        interactions: [{ request: { method: 'POST', path: '/graphql', body: { query: '{ a }' } }, response: { status: 200 } }],
        messages: [{ description: 'm' }],
      }),
    );
    expect(graphql.interactions).toBe(2);
    expect(graphql.kinds).toEqual(['GraphQL', 'Message']);
  });

  it.each([
    ['not JSON', '{', 'Not a pact: the file is not JSON.'],
    ['an array', '[]', 'Not a pact: the file is not a JSON object.'],
    ['no consumer', JSON.stringify({ provider: { name: 'B' }, interactions: [] }), 'Not a pact: missing consumer.'],
    ['no provider', JSON.stringify({ consumer: { name: 'A' }, interactions: [] }), 'Not a pact: missing provider.'],
    ['an empty name', JSON.stringify({ consumer: { name: ' ' }, provider: { name: 'B' }, interactions: [] }), 'Not a pact: the consumer name is missing or empty.'],
    ['no interactions', JSON.stringify({ consumer: { name: 'A' }, provider: { name: 'B' } }), 'Not a pact: there is no interactions or messages list.'],
    ['interactions not a list', JSON.stringify({ consumer: { name: 'A' }, provider: { name: 'B' }, interactions: {} }), 'Not a pact: interactions must be a list.'],
    ['bad metadata', JSON.stringify({ consumer: { name: 'A' }, provider: { name: 'B' }, interactions: [], metadata: 1 }), 'Not a pact: metadata must be an object.'],
    [
      'an HTTP interaction with no method',
      JSON.stringify({ consumer: { name: 'A' }, provider: { name: 'B' }, interactions: [{ request: {}, response: {} }] }),
      'Interaction 1 has no request method.',
    ],
    [
      'a status that is not a whole number',
      JSON.stringify({ consumer: { name: 'A' }, provider: { name: 'B' }, interactions: [{ request: { method: 'GET' }, response: { status: '200' } }] }),
      'Interaction 1 has a response status that is not a whole number.',
    ],
  ])('marks %s with the reason', (_name, text, problem) => {
    expect(readPactFile('x', 'x.json', text).problem).toBe(problem);
  });

  it('refuses a document over the size limit without parsing it', () => {
    expect(readPactFile('x', 'big.json', ' '.repeat(8 * 1024 * 1024 + 1)).problem).toMatch(/Too large/);
  });

  it('marks a second file for the same pair and leaves the first', () => {
    const rows = annotateRows([
      readPactFile('a', 'one.json', pact()),
      readPactFile('b', 'two.json', pact('orders ui', 'billing-service')),
      readPactFile('c', 'bad.json', '{'),
    ]);
    expect(rows[0].problem).toBeNull();
    expect(rows[1].problem).toBe('one.json is also orders ui → billing-service: a consumer version publishes one pact per provider.');
    expect(publishableRows(rows).map((row) => row.id)).toEqual(['a']);
    expect(pacticipantKey('  Billing  Service! ')).toBe('billing-service');
  });
});

describe('whose version', () => {
  it('asks for a version and checks every field', () => {
    expect(validateWhose(EMPTY_WHOSE)).toMatch(/consumer version/);
    expect(validateWhose(WHOSE)).toBeNull();
    expect(validateWhose({ ...WHOSE, buildUrl: 'ftp://x' })).toBe('The build URL must be an http(s) URL.');
    expect(validateWhose({ ...WHOSE, branch: '', tagWithBranch: true })).toBe('Also tag with the branch name needs a branch.');
    expect(validateWhose({ ...WHOSE, version: 'v'.repeat(256) })).toMatch(/longer than 255/);
    expect(validateWhose({ ...WHOSE, tags: Array.from({ length: 51 }, (_, i) => `t${i}`).join(' ') })).toBe('At most 50 tags.');
  });

  it('refuses Merge with the CLI’s reason', () => {
    expect(validateWhose({ ...WHOSE, merge: true })).toBe(MERGE_REFUSED);
    expect(MERGE_REFUSED).toMatch(/--merge is refused/);
  });

  it('adds the branch as a tag only when asked, once', () => {
    expect(effectiveTags(WHOSE)).toEqual(['dev']);
    expect(effectiveTags({ ...WHOSE, tagWithBranch: true })).toEqual(['dev', 'feature/credit-notes']);
    expect(effectiveTags({ ...WHOSE, tags: 'main', branch: 'main', tagWithBranch: true })).toEqual(['main']);
  });
});

describe('publishing', () => {
  it('sends one request per consumer, as the CLI does', () => {
    const rows = [
      readPactFile('a', 'a.json', pact('Orders UI', 'Billing Service')),
      readPactFile('b', 'b.json', pact('Orders UI', 'Orders API')),
      readPactFile('c', 'c.json', pact('Checkout', 'Payments')),
      readPactFile('d', 'd.json', '{'),
    ];
    const batches = publishBatches(rows, { ...WHOSE, tagWithBranch: true, buildUrl: 'https://ci/1' });
    expect(batches.map((batch) => [batch.consumer, batch.rows.map((row) => row.id)])).toEqual([
      ['Orders UI', ['a', 'b']],
      ['Checkout', ['c']],
    ]);
    expect(batches[0].body).toEqual({
      consumerName: 'Orders UI',
      version: '3.4.0',
      branch: 'feature/credit-notes',
      tags: ['dev', 'feature/credit-notes'],
      buildUrl: 'https://ci/1',
      pacts: [
        { providerName: 'Billing Service', pact: rows[0].text },
        { providerName: 'Orders API', pact: rows[1].text },
      ],
    });
  });

  it('splits a consumer with more than 100 pacts', () => {
    const rows = Array.from({ length: 101 }, (_, i) => readPactFile(`r${i}`, `${i}.json`, pact('A', `P${i}`)));
    expect(publishBatches(rows, WHOSE).map((batch) => batch.rows.length)).toEqual([100, 1]);
  });

  it('reads new, unchanged and changed pacts from the notices', () => {
    const outcome = readPublishOutcome('Orders UI', {
      notices: [
        { type: 'debug', text: 'Created Orders UI version 3.4.0 with branch feature/x' },
        { type: 'success', text: 'Pact successfully published for Orders UI version 3.4.0 and provider Billing Service.' },
        { type: 'debug', text: '  View the published pact at http://x' },
        { type: 'success', text: 'Pact successfully republished for Orders UI version 3.4.0 and provider Orders API with no content changes.' },
        { type: 'warning', text: 'Pact with changed content published for Orders UI version 3.4.0 and provider Ledger.' },
      ],
      _links: { 'pb:contracts': [{ pactVersionSha: 'aaa111' }, { pactVersionSha: '8d2f1c0ffee' }, { pactVersionSha: 'ccc' }] },
      comparisons: { compared: 2 },
    });
    expect(outcome.pacts).toEqual([
      { provider: 'Billing Service', state: 'new', sha: 'aaa111' },
      { provider: 'Orders API', state: 'unchanged', sha: '8d2f1c0ffee' },
      { provider: 'Ledger', state: 'changed', sha: 'ccc' },
    ]);
    expect(outcome.compared).toBe(2);
    expect(outcome.notices).toHaveLength(5);
    expect(publishedSentence(outcome.pacts[0])).toMatch(/^new content, pending for Billing Service/);
    expect(publishedSentence(outcome.pacts[1])).toBe('unchanged since 8d2f1c0: its verification results still apply, nothing to do.');
    expect(readPublishOutcome('x', null)).toEqual({ consumer: 'x', pacts: [], notices: [], compared: 0 });
  });

  it('finds the contract a refusal names', () => {
    expect(refusedContractIndex("contract 1 (Orders API): the request method must be a non-empty string")).toBe(1);
    expect(refusedContractIndex('Publishing is rate limited')).toBeNull();
  });
});

describe('check only', () => {
  const row = readPactFile('a', 'a.json', pact());
  const stored = (document: Record<string, unknown>) => ({
    ...document,
    createdAt: '2026-11-27T00:00:00Z',
    _links: { 'pb:pact-version': { href: 'http://x/pacts/provider/b/consumer/a/pact-version/8d2f1c0aa' } },
  });

  it('calls a version with no pact new', () => {
    expect(classifyCheck(row, 404, { success: false })).toEqual({ kind: 'new' });
    expect(checkSentence({ kind: 'new' }, '3.4.0')).toBe('Nothing is published for 3.4.0 yet: this pact will be new.');
  });

  it('calls the same content unchanged, whatever the key order or metadata', () => {
    const document = JSON.parse(row.text);
    const reordered = { metadata: { pactSpecification: { version: '3.0.0' }, client: 'x' }, interactions: document.interactions.map((i: object) => Object.fromEntries(Object.entries(i).reverse())) };
    const verdict = classifyCheck(row, 200, stored(reordered));
    expect(verdict).toEqual({ kind: 'unchanged', sha: '8d2f1c0aa' });
    expect(checkSentence(verdict, '3.4.0')).toBe('Unchanged since 8d2f1c0: its verification results still apply.');
  });

  it('calls different content a conflict and says why', () => {
    const verdict = classifyCheck(row, 200, stored({ interactions: [], metadata: { pactSpecification: { version: '3.0.0' } } }));
    expect(verdict.kind).toBe('conflict');
    expect(checkSentence(verdict, '3.4.0')).toMatch(/^3\.4\.0 already has a different pact\. Use a new version/);
  });

  it('counts a different specification as different content', () => {
    const left = { interactions: [], metadata: { pactSpecification: { version: '3.0.0' } } };
    expect(samePactContent(left, { interactions: [], metadata: { pactSpecification: { version: '4.0' } } })).toBe(false);
    expect(samePactContent(left, { interactions: [], metadata: { 'pact-specification': { version: '3.0.0' } } })).toBe(true);
  });

  it('reports a failed read instead of guessing', () => {
    expect(classifyCheck(row, 403, { success: false, error: 'Permission denied' })).toEqual({ kind: 'error', message: 'Permission denied' });
    expect(classifyCheck(row, 500, null)).toEqual({ kind: 'error', message: 'The check failed (500).' });
    expect(pactVersionSha({})).toBeNull();
  });
});

describe('derive from a project', () => {
  it('checks the tab', () => {
    expect(validateDerive(EMPTY_DERIVE)).toMatch(/project/);
    expect(validateDerive({ ...EMPTY_DERIVE, project: 'billing' })).toMatch(/consumer/);
    expect(validateDerive({ ...EMPTY_DERIVE, project: 'billing', consumer: 'orders-ui', revision: '0' })).toMatch(/whole number/);
    expect(validateDerive({ ...EMPTY_DERIVE, project: 'billing', consumer: 'orders-ui', revision: '3' })).toBeNull();
  });

  it('reads the findings, the pact and the broker’s result', () => {
    const outcome = readDeriveOutcome({
      consumer_name: 'Orders UI',
      revision: 4,
      findings: [{ outcome: 'placeholder', message: 'No example for amount', method: 'GET', path: '/invoices' }, { bad: true }],
      pact: { consumer: { name: 'Orders UI' } },
      publish: { notices: [{ text: 'Pact successfully published for Orders UI version 1 and provider Billing.' }] },
    });
    expect(outcome).toMatchObject({ consumer: 'Orders UI', revision: 4, pact: { consumer: { name: 'Orders UI' } } });
    expect(outcome.findings).toHaveLength(1);
    expect(outcome.pacts).toEqual([{ provider: 'Billing', state: 'new', sha: null }]);
  });
});

describe('arriving pre-filled', () => {
  it('reads the fields and reports what it cannot use', () => {
    const prefill = readPublishPrefill({ version: '9f3c2a1', tag: ['dev', 'rc'], branch: ['main', 'x'], source: 'paste', bogus: '1' });
    expect(prefill.whose).toMatchObject({ version: '9f3c2a1', tags: 'dev, rc', branch: 'main' });
    expect(prefill.source).toBe('paste');
    expect(prefill.problems).toEqual(['?bogus= is not something this page reads.', '?branch= was given more than once; the first is used.']);
    expect(readPublishPrefill({ source: 'record' }).problems).toEqual(['?source=record is not a way in (upload, paste or derive).']);
    expect(readPublishPrefill({ version: 'v'.repeat(300) }).problems[0]).toMatch(/longer than 255/);
  });

  it('builds the address the import dialog links to', () => {
    expect(publishRoute()).toBe('/ade/dashboard/pacts/publish');
    expect(publishRoute({ source: 'paste', version: '1.0', branch: '', tags: ['a', 'b'] })).toBe(
      '/ade/dashboard/pacts/publish?source=paste&version=1.0&tag=a&tag=b',
    );
    const round = readPublishPrefill(Object.fromEntries(new URLSearchParams('source=paste&version=1.0').entries()));
    expect(round.problems).toEqual([]);
  });
});

describe('the same, from anywhere', () => {
  const rows = [readPactFile('a', 'a.json', pact())];

  it('writes the upload as apiome pact publish pacts/ with the form’s flags', () => {
    const action = publishCommandAction({ source: 'upload', rows, whose: { ...WHOSE, tagWithBranch: true, buildUrl: 'https://ci/1' }, derive: EMPTY_DERIVE, tenant: 'acme' });
    const [apiome, pactCli, github, rest] = pactCommandSurfaces(action);
    expect(apiome.text).toContain('apiome pact publish pacts/');
    expect(apiome.text).toContain('--consumer-app-version 3.4.0');
    expect(apiome.text).toContain('--branch feature/credit-notes');
    expect(apiome.text).toContain('--tag dev');
    expect(apiome.text).toContain('--tag-with-git-branch');
    expect(apiome.text).toContain('--build-url https://ci/1');
    expect(pactCli.text).toContain('pact-broker publish pacts/');
    expect(github.text).toContain('command: publish');
    expect(github.text).toContain('pacts: pacts/');
    expect(rest.text).toContain('POST /v1/tenants/acme/pact-broker/contracts/publish');
    expect(rest.text).toContain('"providerName": "Billing Service"');
    expect(unsupportedLines(action)).toEqual([]);
  });

  it('lists Merge and several consumers as not carried, with the reason', () => {
    const two = [...rows, readPactFile('b', 'b.json', pact('Checkout', 'Payments'))];
    const action = publishCommandAction({ source: 'paste', rows: two, whose: { ...WHOSE, merge: true }, derive: EMPTY_DERIVE, tenant: '' });
    const lines = unsupportedLines(action);
    expect(lines[0]).toMatch(/^Merge is not carried by the command: apiome pact publish --merge is refused/);
    expect(lines[1]).toMatch(/^2 consumers is not carried/);
    expect(pactCommandSurfaces(action)[3].text).toContain('/v1/tenants/{tenant}/');
  });

  it('writes a derive as publish-consumer-contract', () => {
    const action = publishCommandAction({
      source: 'derive',
      rows: [],
      whose: WHOSE,
      derive: { project: 'billing', consumer: 'orders-ui', revision: '3', provider: 'Billing Service' },
      tenant: 'acme',
    });
    const [apiome, pactCli, , rest] = pactCommandSurfaces(action);
    expect(apiome.text).toContain('apiome pact publish-consumer-contract');
    expect(apiome.text).toContain('--project billing');
    expect(apiome.text).toContain('--revision 3');
    expect(apiome.text).toContain("--provider 'Billing Service'");
    expect(pactCli.text).toBeNull();
    expect(rest.text).toContain('POST /v1/tenants/acme/projects/billing/consumers/orders-ui/pact/publish');
  });

  it('maps every flag of both commands to a field, and the ledger says the same', () => {
    const commands = JSON.parse(readFileSync(join(__dirname, '..', '..', 'apiome-cli', 'pact-commands.json'), 'utf8')).commands as Array<{
      name: string;
      arguments: string[];
      options: string[];
    }>;
    const ledger = JSON.parse(readFileSync(join(__dirname, '..', '..', 'docs', 'pact-parity-ledger.json'), 'utf8')).commands as Array<{
      cli: string;
      ui: string | null;
      fields?: Record<string, string>;
    }>;
    for (const name of ['publish', 'publish-consumer-contract'] as const) {
      const command = commands.find((c) => c.name === name)!;
      expect(Object.keys(PUBLISH_FLAG_FIELDS[name]).sort()).toEqual([...command.arguments, ...command.options].sort());
      const row = ledger.find((r) => r.cli === name)!;
      expect(row.ui).toBe('/ade/dashboard/pacts/publish');
      expect(row.fields).toEqual(PUBLISH_FLAG_FIELDS[name]);
    }
  });
});

describe('/api/pact/publish with several pacts', () => {
  const body = { consumerName: 'Orders UI', version: '3.4.0', pacts: [{ providerName: 'Billing', pact: pact() }, { providerName: 'Ledger', pact: pact('Orders UI', 'Ledger') }] };

  it('sends every pact in one REST request', () => {
    const picked = pickPublishBody({ ...body, tags: ['dev'] });
    expect(picked.ok).toBe(true);
    const rest = (picked as { body: { contracts: Array<{ providerName: string; content: string }>; tags: string[] } }).body;
    expect(rest.contracts.map((c) => c.providerName)).toEqual(['Billing', 'Ledger']);
    expect(Buffer.from(rest.contracts[1].content, 'base64').toString('utf8')).toBe(body.pacts[1].pact);
    expect(rest.tags).toEqual(['dev']);
  });

  it.each([
    [{ ...body, pact: 'x' }, 'Send either pacts or providerName and pact, not both.'],
    [{ ...body, pacts: [] }, 'pacts must be a non-empty list.'],
    [{ ...body, pacts: [{ providerName: 'B', pact: 'x', extra: 1 }] }, 'Unsupported field pacts[0].extra: an entry takes providerName, pact.'],
    [{ ...body, pacts: [{ providerName: '', pact: 'x' }] }, 'pacts[0].providerName is required.'],
    [{ ...body, pacts: ['x'] }, 'pacts[0] must be an object.'],
    [{ ...body, pacts: Array.from({ length: 101 }, () => ({ providerName: 'B', pact: 'x' })) }, 'pacts takes at most 100.'],
  ])('refuses a malformed list (%#)', (raw, error) => {
    expect(pickPublishBody(raw)).toEqual({ ok: false, error });
  });
});

describe('/api/pact/publish/check', () => {
  const check = (query: string) => CHECK(new NextRequest(`http://x/api/pact/publish/check?${query}`));

  it('reads the pact of that version by name, as the user', async () => {
    const response = await check('consumer=Orders+UI&provider=Billing+Service&version=3.4.0');
    expect(response.status).toBe(200);
    expect(forwarded).toEqual([
      { url: 'http://rest/v1/tenants/acme/pact-broker/pacts/provider/Billing%20Service/consumer/Orders%20UI/version/3.4.0', method: 'GET', body: undefined },
    ]);
  });

  it.each([
    ['consumer=A&provider=B&version=1&x=1', 'Unsupported parameter x: a check takes consumer, provider and version.'],
    ['consumer=A&consumer=B&provider=B&version=1', 'The consumer parameter is given more than once.'],
    ['provider=B&version=1', 'consumer is required.'],
    ['consumer=A&provider=B', 'The version is empty.'],
    ['consumer=A&provider=B&version=a/b', 'A version containing "/" cannot be opened here.'],
  ])('refuses %s without calling REST', async (query, error) => {
    const response = await check(query);
    expect(response.status).toBe(400);
    expect(await response.json()).toEqual({ success: false, error });
    expect(forwarded).toHaveLength(0);
  });

  it('refuses an oversized name', () => {
    expect(pickCheckQuery(new URLSearchParams({ consumer: 'a'.repeat(256), provider: 'B', version: '1' }))).toEqual({
      ok: false,
      error: 'consumer is longer than 255 characters.',
    });
  });
});

describe('/api/pact/publish/consumer-contract', () => {
  const post = (body: unknown) =>
    DERIVE(new Request('http://x/api/pact/publish/consumer-contract', { method: 'POST', body: JSON.stringify(body) }) as never);

  it('forwards REST’s body to the consumer’s publish route', async () => {
    const response = await post({ project: 'billing', consumer: 'orders-ui', version: '3.4.0', tags: ['dev'], buildUrl: 'https://ci/1', revision: 3, provider: 'Billing' });
    expect(response.status).toBe(200);
    expect(forwarded).toEqual([
      {
        url: 'http://rest/v1/tenants/acme/projects/billing/consumers/orders-ui/pact/publish',
        method: 'POST',
        body: { consumer_version: '3.4.0', tags: ['dev'], build_url: 'https://ci/1', revision: 3, provider: 'Billing' },
      },
    ]);
  });

  it.each([
    [{ project: 'p', consumer: 'c', version: '1', extra: 1 }, /^Unsupported field extra/],
    [{ project: 'p', consumer: 'c' }, /^version is required/],
    [{ project: 'p', consumer: 'c', version: '1', revision: 0 }, /^revision must be a whole number/],
    [{ project: 'p', consumer: 'c', version: '1', buildUrl: 'nope' }, /^buildUrl must be an http/],
    [{ project: 'p', consumer: 'c', version: '1', tags: [''] }, /^tags must be a list/],
    [{ project: 1, consumer: 'c', version: '1' }, /^project must be a string/],
  ])('refuses a malformed body without calling REST (%#)', async (body, error) => {
    const response = await post(body);
    expect(response.status).toBe(400);
    expect((await response.json()).error).toMatch(error);
    expect(forwarded).toHaveLength(0);
  });

  it('refuses a body that is not JSON', async () => {
    const response = await DERIVE(new Request('http://x', { method: 'POST', body: 'nope' }) as never);
    expect(response.status).toBe(400);
    expect(pickDeriveBody(null)).toEqual({ ok: false, error: 'The body must be a JSON object describing the publication.' });
  });
});
