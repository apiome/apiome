/**
 * @jest-environment node
 */
/**
 * The Export page's model — PFX-8.18 (#7315): `lib/pact-export.ts` and `lib/zip-store.ts`.
 *
 * * the prefill reads `?kind=` and the pair, and reports anything it cannot use;
 * * the derive proxy query is checked and built; REST's operations become the checklist, each with
 *   where its examples came from or why it was left out; unticked operations leave the download;
 * * the Postman form is checked, becomes `export-postman`'s body, and the proxy refuses an unknown,
 *   mistyped or oversized field; the fidelity bar and file name come from REST's answer;
 * * the pact-file queries map to the broker paths, a stored pact loses only the broker's decoration;
 * * the command blocks carry every form value, and list what no command carries with its reason;
 * * every flag of both commands has a control, as the ledger says;
 * * the zip writer's archive is one `unzip` reads back.
 */

import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import ledger from '../../docs/pact-parity-ledger.json';
import commands from '../../apiome-cli/pact-commands.json';
import {
  choiceProblem,
  consumerPactUrl,
  deriveExportAction,
  EMPTY_DERIVE_EXPORT,
  EMPTY_PACT_FILE,
  EMPTY_POSTMAN,
  EXCLUDED_REASON,
  EXPORT_FLAG_FIELDS,
  exportRoute,
  fidelity,
  fileStem,
  noPactMessage,
  pactFileAction,
  pactFilePath,
  pactFileUrl,
  pactWithout,
  pickConsumerPactQuery,
  pickPactFileQuery,
  pickPostmanBody,
  postmanExportAction,
  postmanFileName,
  postmanRequestBody,
  previewable,
  PREVIEW_LIMIT_CHARS,
  readDerivedPact,
  readExportPrefill,
  readPostmanOutcome,
  readUploadedPact,
  sizeLabel,
  storedPact,
  validatePactFile,
  validatePostman,
  validateProviderPacts,
} from '../lib/pact-export';
import { pactCommandSurfaces, unsupportedLines } from '../lib/pact-commands';
import { crc32, createZip } from '../lib/zip-store';

/** REST's answer for a consumer with three declared operations. */
const DERIVED = {
  consumer_name: 'Orders UI',
  provider_name: 'Billing Service',
  revision: 4,
  version_label: '2.7.0',
  interaction_count: 3,
  findings: [
    { outcome: 'placeholder', reason: 'no-example', message: 'no example for total', method: 'POST', path: '/invoices', status: '201', location: 'response', field: 'total' },
    { outcome: 'omitted', reason: 'no-response-declared', message: 'the operation declares no responses', method: 'DELETE', path: '/invoices/{id}' },
    { outcome: 'omitted', reason: 'contract-unresolved', message: 'a field could not be resolved' },
  ],
  operations: [
    { method: 'GET', path: '/invoices/{id}', operation_id: 'getInvoice', interactions: [0, 1], placeholder_count: 0, omitted_count: 0 },
    { method: 'POST', path: '/invoices', operation_id: null, interactions: [2], placeholder_count: 1, omitted_count: 0 },
    { method: 'DELETE', path: '/invoices/{id}', operation_id: null, interactions: [], placeholder_count: 0, omitted_count: 1 },
  ],
  pact: {
    consumer: { name: 'Orders UI' },
    provider: { name: 'Billing Service' },
    interactions: [{ description: 'getInvoice returns 200' }, { description: 'getInvoice returns 404' }, { description: 'POST /invoices returns 201' }],
    metadata: { pactSpecification: { version: '4.0' } },
  },
};

describe('the prefill and the route', () => {
  it('reads the kind and the pair, and reports what it cannot use', () => {
    const prefill = readExportPrefill({ kind: 'file', provider: 'billing', consumer: 'orders-ui', version: '3.4.0', colour: 'red' });
    expect(prefill).toMatchObject({ kind: 'file', provider: 'billing', consumer: 'orders-ui', version: '3.4.0' });
    expect(prefill.problems).toEqual(['?colour= is not something this page reads.']);
    expect(readExportPrefill({ kind: 'tests' }).problems[0]).toContain('?kind=tests is not something to export');
    expect(readExportPrefill({ kind: 'tests' }).kind).toBe('pact');
    expect(readExportPrefill({ provider: ['a', 'b'] })).toMatchObject({ provider: 'a', problems: ['?provider= was given more than once; the first is used.'] });
    expect(readExportPrefill({ consumer: 'x'.repeat(300) })).toMatchObject({ consumer: '' });
  });

  it('links with only the fields given', () => {
    expect(exportRoute()).toBe('/ade/dashboard/pacts/export');
    expect(exportRoute({ kind: 'postman', provider: 'billing', consumer: ' ' })).toBe('/ade/dashboard/pacts/export?kind=postman&provider=billing');
  });

  it('says what a pair without a pact can do', () => {
    expect(noPactMessage('Orders UI', 'Billing Service')).toBe(
      'Orders UI has not published a pact for Billing Service. Record one from a mock, or upload a file.',
    );
  });

  it('previews small outputs only, and names sizes', () => {
    expect(previewable('x'.repeat(PREVIEW_LIMIT_CHARS))).toBe(true);
    expect(previewable('x'.repeat(PREVIEW_LIMIT_CHARS + 1))).toBe(false);
    expect([sizeLabel(812), sizeLabel(14_540), sizeLabel(3_250_000)]).toEqual(['812 B', '14.2 KB', '3.1 MB']);
    expect(fileStem('Orders UI', 'Billing Service')).toBe('orders-ui-billing-service');
    expect(fileStem('!!!')).toBe('pact');
  });
});

describe('a pact from a project', () => {
  it('builds the proxy URL and checks the proxy query', () => {
    const draft = { ...EMPTY_DERIVE_EXPORT, project: 'billing-api', consumer: 'orders-ui', revision: '4', provider: 'Billing Service' };
    expect(consumerPactUrl(draft)).toBe('/api/pact/export/consumer-pact?project=billing-api&consumer=orders-ui&revision=4&provider=Billing+Service');
    expect(pickConsumerPactQuery(new URLSearchParams('project=billing-api&consumer=orders-ui&revision=4&provider=Billing%20Service'))).toEqual({
      ok: true,
      path: 'projects/billing-api/consumers/orders-ui/pact?revision=4&provider=Billing+Service',
    });
    expect(pickConsumerPactQuery(new URLSearchParams('project=p&consumer=c'))).toEqual({ ok: true, path: 'projects/p/consumers/c/pact' });
  });

  it.each([
    ['project=p&consumer=c&format=v3', 'Unsupported parameter format'],
    ['project=p&project=q&consumer=c', 'given more than once'],
    ['consumer=c', 'Pick the project'],
    ['project=p', 'Pick the consumer'],
    ['project=p&consumer=c&revision=0', 'whole number'],
    [`project=p&consumer=c&provider=${'x'.repeat(201)}`, 'longer than 200'],
  ])('refuses %s', (query, error) => {
    const picked = pickConsumerPactQuery(new URLSearchParams(query));
    expect(picked.ok).toBe(false);
    expect(picked.ok ? '' : picked.error).toContain(error);
  });

  it('reads the checklist: the spec’s example, generated, or left out with the reason', () => {
    const derived = readDerivedPact(DERIVED)!;
    expect(derived.operations.map((row) => [row.key, row.source, row.note])).toEqual([
      ['GET /invoices/{id}', 'spec', 'The spec’s example'],
      ['POST /invoices', 'generated', 'Generated from the schema — review (1 value)'],
      ['DELETE /invoices/{id}', 'left-out', 'Left out — the operation declares no responses'],
    ]);
    expect(derived.generalFindings.map((finding) => finding.reason)).toEqual(['contract-unresolved']);
    expect(derived).toMatchObject({ consumerName: 'Orders UI', providerName: 'Billing Service', revision: 4, versionLabel: '2.7.0' });
    expect(readDerivedPact({ findings: [] })).toBeNull();
  });

  it('leaves unticked operations out of the download, and nothing else', () => {
    const derived = readDerivedPact(DERIVED)!;
    expect(pactWithout(derived, new Set())).toBe(derived.pact);
    const without = pactWithout(derived, new Set(['GET /invoices/{id}']));
    expect(without.interactions).toEqual([{ description: 'POST /invoices returns 201' }]);
    expect(without.metadata).toEqual(DERIVED.pact.metadata);
  });

  it('is export-consumer-contract, and says why unticked operations are not in it', () => {
    const draft = { ...EMPTY_DERIVE_EXPORT, project: 'billing-api', consumer: 'orders-ui', revision: '4', failOnFindings: true };
    const action = deriveExportAction(draft, { tenant: 'acme', excluded: ['GET /invoices/{id}'] });
    const [apiome, , , rest] = pactCommandSurfaces(action);
    expect(apiome.text).toContain('apiome pact export-consumer-contract');
    expect(apiome.text).toContain('--project billing-api');
    expect(apiome.text).toContain('--revision 4');
    expect(apiome.text).toContain('--output pact.json');
    expect(apiome.text).toContain('--fail-on-findings');
    expect(apiome.text).not.toContain('--provider');
    expect(rest.text).toContain('GET /v1/tenants/acme/projects/billing-api/consumers/orders-ui/pact?revision=4');
    expect(unsupportedLines(action)).toEqual([`Leaving out GET /invoices/{id} is not carried by the command: ${EXCLUDED_REASON}`]);
    expect(unsupportedLines(deriveExportAction(draft, { tenant: '', excluded: [] }))).toEqual([]);
  });
});

describe('a Postman collection', () => {
  const stored = { ...EMPTY_POSTMAN, provider: 'Billing Service', consumer: 'Orders UI', choice: 'branch' as const, choiceValue: 'main', baseUrl: 'http://localhost:8080' };

  it('becomes the body export-postman sends', () => {
    expect(postmanRequestBody(stored)).toEqual({
      tests: true,
      provider: 'Billing Service',
      consumer: 'Orders UI',
      branch: 'main',
      baseUrl: 'http://localhost:8080',
      stateSetup: true,
    });
    expect(postmanRequestBody({ ...stored, allConsumers: true, choice: 'tag', choiceValue: 'prod', stateSetup: true, stateChangeUrl: 'http://p/_pact/states', tests: false, baseUrl: '' })).toEqual({
      tests: false,
      provider: 'Billing Service',
      allConsumers: true,
      tag: 'prod',
      stateSetup: true,
      stateChangeUrl: 'http://p/_pact/states',
    });
    const file = { ...EMPTY_POSTMAN, source: 'file' as const, fileName: 'p.json', fileText: '{"consumer":{"name":"a"}}', stateSetup: false };
    expect(postmanRequestBody(file)).toEqual({ tests: true, pact: { consumer: { name: 'a' } } });
  });

  it.each([
    [{ ...EMPTY_POSTMAN }, 'Provider is required.'],
    [{ ...EMPTY_POSTMAN, provider: 'p' }, 'Consumer is required.'],
    [{ ...EMPTY_POSTMAN, provider: 'p', consumer: 'c', choice: 'branch' as const }, 'Branch is required'],
    [{ ...EMPTY_POSTMAN, provider: 'p', consumer: 'c', choice: 'sha' as const, choiceValue: 'abc' }, '64 hexadecimal'],
    [{ ...EMPTY_POSTMAN, provider: 'p', allConsumers: true, choice: 'version' as const, choiceValue: '1' }, 'names one consumer’s pact'],
    [{ ...EMPTY_POSTMAN, provider: 'p', consumer: 'c', baseUrl: 'localhost:8080' }, 'Provider base URL'],
    [{ ...EMPTY_POSTMAN, provider: 'p', consumer: 'c', stateChangeUrl: 'ftp://x' }, 'State change URL'],
    [{ ...EMPTY_POSTMAN, source: 'file' as const }, 'Choose the pact file'],
    [{ ...EMPTY_POSTMAN, source: 'file' as const, fileText: '[1]' }, 'A Pact file is a JSON object.'],
    [{ ...EMPTY_POSTMAN, source: 'file' as const, fileText: 'nope' }, 'The file is not JSON.'],
  ])('checks the form (%#)', (draft, problem) => {
    expect(validatePostman(draft)).toContain(problem);
  });

  it('passes a good form', () => {
    expect(validatePostman(stored)).toBeNull();
    expect(validatePostman({ ...EMPTY_POSTMAN, provider: 'p', allConsumers: true })).toBeNull();
    expect(readUploadedPact('{}')).toEqual({ ok: true, pact: {} });
  });

  it.each([
    [null, 'must be a JSON object'],
    [{ provider: 'p', format: 'v2' }, 'Unsupported field format'],
    [{ provider: 1 }, 'provider must be a string'],
    [{ provider: 'x'.repeat(256) }, 'longer than 255'],
    [{ baseUrl: 5 }, 'baseUrl must be a URL'],
    [{ tests: 'yes' }, 'tests must be true or false'],
    [{ allConsumers: 1 }, 'allConsumers must be true or false'],
    [{ pact: [] }, 'pact must be a Pact document'],
  ])('the proxy refuses %p', (raw, error) => {
    const picked = pickPostmanBody(raw);
    expect(picked.ok).toBe(false);
    expect(picked.ok ? '' : picked.error).toContain(error);
  });

  it('the proxy forwards a good body unchanged', () => {
    const body = { provider: 'p', allConsumers: true, stateSetup: true, stateChangeUrl: 'http://x', tests: false };
    expect(pickPostmanBody(body)).toEqual({ ok: true, body });
  });

  it('reads the answer: counts, notices, consumers, the fidelity bar and the file name', () => {
    const one = readPostmanOutcome({
      collection: { info: {}, item: [] },
      pact: { consumer: 'Orders UI', provider: 'Billing Service' },
      counts: { interactions: 6, exported: 5, leftOut: 1 },
      notices: [{ code: 'pact-postman-message-left-out', outcome: 'left-out', pointer: '/messages/0', message: 'a message interaction has no HTTP request' }, { bad: true }],
    })!;
    expect(one.consumers).toEqual(['Orders UI']);
    expect(one.notices).toHaveLength(1);
    expect(fidelity(one.counts)).toEqual({ kept: 5, leftOut: 1, total: 6, keptPercent: 83 });
    expect(postmanFileName(one)).toBe('orders-ui-billing-service.postman.json');
    const every = readPostmanOutcome({ collection: {}, pact: { provider: 'Billing', consumers: [{ consumer: 'A' }, { consumer: 'B' }] } })!;
    expect(every.consumers).toEqual(['A', 'B']);
    expect(postmanFileName(every)).toBe('every-consumer-billing.postman.json');
    expect(fidelity({ interactions: 0, exported: 0, leftOut: 0 }).keptPercent).toBe(100);
    expect(readPostmanOutcome({ notices: [] })).toBeNull();
  });

  it('is export-postman with every flag the form sets', () => {
    const action = postmanExportAction({ ...stored, allConsumers: true, consumer: '', stateChangeUrl: 'http://p/states', tests: false, failOnLeftOut: true }, 'acme');
    const [apiome, , , rest] = pactCommandSurfaces(action);
    for (const part of ['apiome pact export-postman', '--all-consumers', '--branch main', '--provider-base-url', '--state-setup', '--state-change-url', '--no-tests', '--output collection.json', '--fail-on-left-out']) {
      expect(apiome.text).toContain(part);
    }
    expect(apiome.text).not.toContain('--consumer ');
    expect(rest.text).toContain('POST /v1/tenants/acme/pact-postman-collections');
    const file = pactCommandSurfaces(postmanExportAction({ ...EMPTY_POSTMAN, source: 'file', fileName: 'mine.json', fileText: '{}' }, ''));
    expect(file[0].text).toContain('--pact-file mine.json');
    expect(file[3].text).toContain('<the contents of mine.json>');
  });
});

describe('a pact file', () => {
  it.each([
    ['latest', '', 'pact-broker/pacts/provider/billing/consumer/orders%20ui/latest'],
    ['branch', 'main', 'pact-broker/pacts/provider/billing/consumer/orders%20ui/branch/main/latest'],
    ['tag', 'prod', 'pact-broker/pacts/provider/billing/consumer/orders%20ui/latest/prod'],
    ['version', '3.4.0', 'pact-broker/pacts/provider/billing/consumer/orders%20ui/version/3.4.0'],
    ['sha', 'ab', 'pact-broker/pacts/provider/billing/consumer/orders%20ui/pact-version/ab'],
  ] as const)('maps %s to the broker path', (choice, value, expected) => {
    expect(pactFilePath('billing', 'orders ui', choice, value)).toBe(expected);
  });

  it('builds and checks the proxy queries', () => {
    const draft = { ...EMPTY_PACT_FILE, provider: 'billing', consumer: 'orders-ui', choice: 'tag' as const, choiceValue: 'prod' };
    expect(pactFileUrl(draft)).toBe('/api/pact/export/pact-file?provider=billing&consumer=orders-ui&tag=prod');
    expect(pactFileUrl(draft, true)).toBe('/api/pact/export/provider-pacts?provider=billing&tag=prod');
    expect(pickPactFileQuery(new URLSearchParams('provider=billing&consumer=orders-ui&version=3.4.0'), false)).toEqual({
      ok: true,
      provider: 'billing',
      consumer: 'orders-ui',
      choice: 'version',
      value: '3.4.0',
    });
    expect(pickPactFileQuery(new URLSearchParams('provider=billing'), true)).toEqual({ ok: true, provider: 'billing', consumer: '', choice: 'latest', value: '' });
  });

  it.each([
    ['provider=b&consumer=c&colour=red', false, 'Unsupported parameter colour'],
    ['provider=b&consumer=c&tag=a&branch=b', false, 'Choose one of branch, tag'],
    ['provider=b&provider=c&consumer=c', false, 'more than once'],
    ['consumer=c', false, 'provider is required'],
    ['provider=b', false, 'consumer is required'],
    ['provider=b&consumer=c&sha=zz', false, '64 hexadecimal'],
    ['provider=b&version=1', true, 'Unsupported parameter version'],
    ['provider=b&consumer=c', true, 'Unsupported parameter consumer'],
  ])('refuses %s', (query, every, error) => {
    const picked = pickPactFileQuery(new URLSearchParams(query), every);
    expect(picked.ok).toBe(false);
    expect(picked.ok ? '' : picked.error).toContain(error);
  });

  it('checks the form for one pact and for every pact', () => {
    expect(validatePactFile({ ...EMPTY_PACT_FILE, provider: 'b' })).toBe('Consumer is required.');
    expect(validatePactFile({ ...EMPTY_PACT_FILE, provider: 'b', consumer: 'c' })).toBeNull();
    expect(validateProviderPacts({ ...EMPTY_PACT_FILE, provider: 'b', choice: 'version', choiceValue: '1' })).toContain('names one consumer’s pact');
    expect(validateProviderPacts({ ...EMPTY_PACT_FILE, provider: 'b' })).toBeNull();
    expect(choiceProblem('latest', '')).toBeNull();
  });

  it('downloads a pact exactly as stored', () => {
    const body = { consumer: { name: 'a' }, interactions: [], createdAt: '2026-11-01', _links: { self: {} } };
    expect(storedPact(body)).toEqual({ consumer: { name: 'a' }, interactions: [] });
    expect(body._links).toEqual({ self: {} });
  });

  it('has no command, and says why', () => {
    const action = pactFileAction({ ...EMPTY_PACT_FILE, provider: 'billing', consumer: 'orders-ui' }, 'acme');
    const surfaces = pactCommandSurfaces(action);
    expect(action.verb).toBeNull();
    expect(surfaces[3].text).toContain('GET /v1/tenants/acme/pact-broker/pacts/provider/billing/consumer/orders-ui/latest');
  });
});

describe('the parity ledger', () => {
  it.each(['export-consumer-contract', 'export-postman'] as const)('maps every flag of %s to a control, as the ledger does', (name) => {
    const command = commands.commands.find((row) => row.name === name)!;
    const fields = EXPORT_FLAG_FIELDS[name];
    expect(Object.keys(fields).sort()).toEqual([...command.arguments, ...command.options].sort());
    const row = ledger.commands.find((entry) => entry.cli === name) as { ui: string | null; fields?: Record<string, string>; reason?: string };
    expect(row.ui).toBe('/ade/dashboard/pacts/export');
    expect(row.reason).toBeUndefined();
    expect(row.fields).toEqual(fields);
  });
});

describe('the zip writer', () => {
  it('computes the standard CRC-32', () => {
    expect(crc32(new TextEncoder().encode('123456789'))).toBe(0xcbf43926);
    expect(crc32(new Uint8Array())).toBe(0);
  });

  it('writes an archive unzip reads back', () => {
    const encoder = new TextEncoder();
    const archive = createZip([
      { name: 'orders-ui-billing.json', data: encoder.encode('{"a":1}\n') },
      { name: 'README.txt', data: encoder.encode('Pacts für Billing\n') },
    ]);
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'pexp-zip-'));
    const file = path.join(dir, 'pacts.zip');
    fs.writeFileSync(file, archive);
    try {
      const listing = execFileSync('unzip', ['-l', file]).toString();
      expect(listing).toContain('orders-ui-billing.json');
      expect(listing).toContain('README.txt');
      expect(execFileSync('unzip', ['-p', file, 'README.txt']).toString()).toBe('Pacts für Billing\n');
      execFileSync('unzip', ['-tq', file]);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === 'ENOENT') return; // no unzip on this machine
      throw error;
    } finally {
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });

  it('refuses an empty, duplicate or unsafe archive', () => {
    const data = new Uint8Array([1]);
    expect(() => createZip([])).toThrow('at least one entry');
    expect(() => createZip([{ name: 'a', data }, { name: 'a', data }])).toThrow('Duplicate');
    expect(() => createZip([{ name: '../a', data }])).toThrow('Unsafe');
    expect(() => createZip([{ name: '/a', data }])).toThrow('Unsafe');
  });
});
