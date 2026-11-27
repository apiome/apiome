/**
 * The **Publish a provider contract** model — PFX-8.6 (#7303), `lib/pact-provider-contract.ts`:
 *
 * * an uploaded document's format pill, media type, or why it cannot be published (a YAML error
 *   with its line, Swagger 2.0, not a contract at all);
 * * the form's problems per field and per evidence choice (Run it now needs a project version and
 *   a target; the pipeline needs a verifier and a whole-number exit code);
 * * the REST bodies: `apiomeVersion`, inline base64 content, `contentUrl` for a check and the
 *   fetched bytes for the publish; `verificationResults` as `apiome pact` builds it;
 * * the command block: every field as its flag, what the command cannot carry listed with a reason;
 * * the check and publish answers read into sentences: the ring, a breaking consumer in
 *   production, Nobody uses, the conflict, the dialog's lines and the notifications line;
 * * every `publish-provider-contract` flag maps to a field (the ledger row).
 */

import { readFileSync } from 'fs';
import { join } from 'path';
import { pactCommandSurfaces, unsupportedLines } from '../lib/pact-commands';
import {
  EMPTY_FORM,
  EVIDENCE_CHOICES,
  NOTIFICATIONS_LINE,
  NO_CONSUMERS,
  PROVIDER_CONTRACT_ROUTE,
  RUN_HAS_NO_FLAG,
  URL_HAS_NO_FLAG,
  asideHeadline,
  canIDeployHref,
  checkRequest,
  conflictSentence,
  detectContract,
  evidenceSentence,
  failingOperations,
  formProblems,
  nobodyUsesSentence,
  providerContractCommandAction,
  publishRequest,
  publishedLines,
  readCheckAnswer,
  readPublishAnswer,
  reportContentType,
  toBase64,
  verdictSentence,
  type ProviderContractForm,
} from '../lib/pact-provider-contract';

const OAS = 'openapi: 3.1.0\ninfo:\n  title: Billing\n  version: 2.7.0\npaths: {}\n';

const form = (patch: Partial<ProviderContractForm> = {}): ProviderContractForm => ({
  ...EMPTY_FORM,
  provider: 'Billing Service',
  providerVersion: '2.7.0+9f31c20',
  project: 'billing-api',
  version: '2.7.0',
  ...patch,
});

const decode = (base64: string) => new TextDecoder().decode(Uint8Array.from(atob(base64), (c) => c.charCodeAt(0)));

describe('reading an uploaded document', () => {
  it('names the format and the media type', () => {
    expect(detectContract(OAS, 'openapi.yaml')).toEqual({ format: 'OpenAPI 3.1', contractType: 'oas', contentType: 'application/yaml', problem: null });
    expect(detectContract('{"asyncapi":"3.0.0","info":{}}', 'events.json')).toMatchObject({
      format: 'AsyncAPI 3.0',
      contractType: 'asyncapi',
      contentType: 'application/json',
    });
  });

  it('says why a document cannot be published', () => {
    expect(detectContract('openapi: 3.1.0\ninfo:\n  title: x\n  bad: value: here\n', 'a.yaml').problem).toMatch(
      /^Could not read this file: line 4, nested mappings are not allowed/,
    );
    expect(detectContract('{"swagger":"2.0"}', 'a.json').problem).toContain('Swagger 2.0');
    expect(detectContract('{"openapi":"2.5"}', 'a.json').problem).toContain('OpenAPI 2.5 is not supported');
    expect(detectContract('{"name":"x"}', 'a.json').problem).toContain('neither an `openapi` nor an `asyncapi`');
    expect(detectContract('[1]', 'a.json').problem).toContain('no top-level object');
    expect(detectContract('  ', 'a.yaml').problem).toBe('The file is empty.');
    expect(detectContract('{', 'a.json').problem).toMatch(/^Could not read this file: /);
  });

  it('infers a report’s media type as the CLI does', () => {
    expect(reportContentType('junit.XML')).toBe('application/xml');
    expect(reportContentType('newman.json')).toBe('application/json');
    expect(reportContentType('run.ndjson')).toBe('application/x-ndjson');
    expect(reportContentType('run.jsonl')).toBe('application/x-ndjson');
    expect(reportContentType('notes.txt')).toBe('text/plain');
    expect(reportContentType('report')).toBeNull();
  });

  it('encodes UTF-8 as base64', () => {
    expect(decode(toBase64('títle ✓'))).toBe('títle ✓');
  });
});

describe('the form’s problems', () => {
  const fields = (f: ProviderContractForm) => formProblems(f).map((p) => p.field);

  it('accepts a complete project-version form with no evidence', () => {
    expect(formProblems(form())).toEqual([]);
  });

  it('names each missing or bad field', () => {
    expect(fields({ ...EMPTY_FORM })).toEqual(['project', 'provider', 'providerVersion']);
    expect(fields(form({ version: '' }))).toEqual(['version']);
    expect(fields(form({ source: 'upload' }))).toEqual(['file']);
    expect(formProblems(form({ source: 'upload', file: { name: 'x.json', text: '{"swagger":"2.0"}' } }))[0].message).toContain('Swagger');
    expect(fields(form({ source: 'url', url: 'ftp://x' }))).toEqual(['url']);
    expect(fields(form({ providerVersion: 'a/b' }))).toEqual(['providerVersion']);
    expect(fields(form({ buildUrl: 'not a url' }))).toEqual(['buildUrl']);
    expect(fields(form({ tags: Array.from({ length: 51 }, (_, i) => `t${i}`).join(',') }))).toEqual(['tags']);
  });

  it('checks each evidence choice’s inputs', () => {
    expect(fields(form({ evidence: 'run' }))).toEqual(['target']);
    expect(formProblems(form({ evidence: 'run', source: 'upload', file: { name: 'a.yaml', text: OAS }, target: 'staging' }))[0].message).toContain(
      'Run it now verifies a project version',
    );
    expect(fields(form({ evidence: 'report' }))).toEqual(['report']);
    expect(fields(form({ evidence: 'reuse' }))).toEqual(['reportId']);
    expect(fields(form({ evidence: 'exit' }))).toEqual(['verifier', 'exitCode']);
    expect(fields(form({ evidence: 'exit', verifier: 'schemathesis', exitCode: 'zero' }))).toEqual(['exitCode']);
    expect(fields(form({ evidence: 'exit', verifier: 'schemathesis', exitCode: '0' }))).toEqual([]);
  });

  it('lists the five choices strongest first, each with its strength', () => {
    expect(EVIDENCE_CHOICES.map((c) => [c.kind, c.strength])).toEqual([
      ['run', 'Strong'],
      ['report', 'Strong'],
      ['reuse', 'Strong'],
      ['exit', 'Weak'],
      ['none', 'None'],
    ]);
  });
});

describe('the requests', () => {
  it('names a project version by apiomeVersion', () => {
    expect(checkRequest(form({ branch: 'main', tags: 'rc' }))).toEqual({
      provider: 'Billing Service',
      providerVersion: '2.7.0+9f31c20',
      body: { apiomeVersion: 'billing-api@2.7.0', branch: 'main' },
    });
    expect(publishRequest(form({ branch: 'main', tags: 'rc, prod', buildUrl: 'https://ci.example.com/1' })).body).toEqual({
      apiomeVersion: 'billing-api@2.7.0',
      branch: 'main',
      tags: ['rc', 'prod'],
      buildUrl: 'https://ci.example.com/1',
    });
  });

  it('sends an upload inline with its type and a URL by address for a check, as the read bytes for a publish', () => {
    const upload = publishRequest(form({ source: 'upload', file: { name: 'openapi.yaml', text: OAS } })).body;
    expect(upload).toMatchObject({ contentType: 'application/yaml', contractType: 'oas' });
    expect(decode(String(upload.content))).toBe(OAS);
    const url = form({ source: 'url', url: ' https://api.example.com/openapi.yaml ' });
    expect(checkRequest(url).body).toEqual({ contentUrl: 'https://api.example.com/openapi.yaml' });
    expect(publishRequest(url, 'b3BlbmFwaQ==').body).toEqual({ content: 'b3BlbmFwaQ==' });
  });

  it('builds verificationResults as apiome pact does', () => {
    const report = { name: 'junit.xml', text: '<testsuite tests="1"/>' };
    expect(publishRequest(form({ evidence: 'report', report })).body.verificationResults).toEqual({
      success: true,
      content: toBase64(report.text),
      contentType: 'application/xml',
    });
    expect(publishRequest(form({ evidence: 'report', report, exitCode: '1', verifier: 'dredd' })).body.verificationResults).toMatchObject({
      success: false,
      verifier: 'dredd',
    });
    expect(publishRequest(form({ evidence: 'reuse', reportId: ' 6f1c ' })).body.verificationResults).toEqual({ providerVerificationReportId: '6f1c' });
    expect(publishRequest(form({ evidence: 'exit', verifier: 'schemathesis', verifierVersion: '3.39.2', exitCode: '0' })).body.verificationResults).toEqual({
      success: true,
      verifier: 'schemathesis',
      verifierVersion: '3.39.2',
    });
    expect(publishRequest(form({ evidence: 'none' })).body.verificationResults).toBeUndefined();
  });

  it('asks the BFF to run the verifier first for Run it now, and sends no evidence of its own', () => {
    const request = publishRequest(form({ evidence: 'run', target: 'staging' }));
    expect(request.run).toEqual({ versionRef: 'project/billing-api/2.7.0', target: 'staging' });
    expect(request.body.verificationResults).toBeUndefined();
  });
});

describe('the command block', () => {
  it('writes the form as apiome pact publish-provider-contract', () => {
    const action = providerContractCommandAction(form({ branch: 'main', evidence: 'reuse', reportId: 'r-1' }), 'acme');
    const [apiome] = pactCommandSurfaces(action);
    expect(apiome.text).toContain('apiome pact publish-provider-contract');
    expect(apiome.text).toContain("--provider 'Billing Service'");
    expect(apiome.text).toContain('--provider-app-version 2.7.0+9f31c20');
    expect(apiome.text).toContain('--apiome-version billing-api@2.7.0');
    expect(apiome.text).toContain('--evidence-report r-1');
    expect(action.rest.path).toBe('/v1/tenants/acme/pact-broker/contracts/provider/Billing%20Service/version/2.7.0%2B9f31c20');
    expect(action.unsupported).toEqual([]);
  });

  it('lists what the command cannot carry, with the reason', () => {
    const url = providerContractCommandAction(form({ source: 'url', url: 'https://api.example.com/o.yaml', evidence: 'run', target: 's' }), '');
    expect(unsupportedLines(url).join('\n')).toContain(URL_HAS_NO_FLAG);
    expect(unsupportedLines(url).join('\n')).toContain(RUN_HAS_NO_FLAG);
    const exit = pactCommandSurfaces(providerContractCommandAction(form({ evidence: 'exit', verifier: 'schemathesis', exitCode: '0' }), ''))[0];
    expect(exit.text).toContain('--verifier schemathesis');
    expect(exit.text).toContain('--verification-exit-code 0');
    const report = pactCommandSurfaces(providerContractCommandAction(form({ evidence: 'report', report: { name: 'junit.xml', text: 'x' } }), ''))[0];
    expect(report.text).toContain('--evidence junit.xml');
  });

  it('gives every flag of the command a field in the ledger', () => {
    const root = join(__dirname, '..', '..');
    const commands = JSON.parse(readFileSync(join(root, 'apiome-cli', 'pact-commands.json'), 'utf8')) as {
      commands: { name: string; arguments: string[]; options: string[] }[];
    };
    const ledger = JSON.parse(readFileSync(join(root, 'docs', 'pact-parity-ledger.json'), 'utf8')) as {
      commands: { cli: string; ui: string | null; fields?: Record<string, string>; reason?: string }[];
    };
    const command = commands.commands.find((c) => c.name === 'publish-provider-contract')!;
    const row = ledger.commands.find((c) => c.cli === 'publish-provider-contract')!;
    expect(row.ui).toBe(PROVIDER_CONTRACT_ROUTE);
    expect(row.reason).toBeUndefined();
    expect(Object.keys(row.fields ?? {}).sort()).toEqual([...command.arguments, ...command.options].sort());
  });
});

describe('reading the answers', () => {
  const check = (patch: Record<string, unknown> = {}) =>
    readCheckAnswer({
      provider: { name: 'Billing Service', exists: true },
      providerVersion: '2.7.0+9f31c20',
      contract: { contractType: 'oas', oasVersion: '3.1.0', operationCount: 12, contentSha: 'ab' },
      selfVerification: { status: 'missing', providerContractVerified: false, reasons: ['no self-verification results were sent'] },
      existing: null,
      summary: { publishable: true },
      results: [
        {
          consumer: 'Orders UI',
          consumerVersion: '3.3.2',
          sha: '8d2f1c00',
          environments: ['production'],
          verdict: 'fail',
          success: false,
          interactions: 3,
          failures: [{ interaction: 'create', operation: 'POST /invoices', code: 'x', message: 'no longer returns currency' }],
          moreFailures: 1,
        },
        { consumer: 'Mobile App', consumerVersion: '5.1.0', sha: '51ab90', environments: [], verdict: 'pass', success: true, interactions: 4, failures: [], moreFailures: 0 },
        { consumer: 'Checkout', consumerVersion: '1.0.0', sha: 'c07e33', environments: [], verdict: null, success: null, reason: 'the pact version no longer exists' },
      ],
      coverage: { operations: 12, used: 7, unused: [{ method: 'DELETE', path: '/invoices/{id}' }, { method: 'GET', path: '/health' }], unusedMore: 0 },
      ...patch,
    });

  it('reads the ring, each consumer and Nobody uses', () => {
    const answer = check();
    expect(answer.format).toBe('OpenAPI 3.1');
    const headline = asideHeadline(answer);
    expect(headline).toMatchObject({ ring: '1/2', tone: 'warn', title: '1 of 2 consumers stay compatible' });
    expect(headline.detail).toContain('1 pact was not compared');
    expect(verdictSentence(answer.results[0])).toBe('POST /invoices: no longer returns currency. And 1 more. Orders UI 3.3.2 is in production.');
    expect(verdictSentence(answer.results[1])).toBe('4 interactions covered.');
    expect(verdictSentence(answer.results[2])).toBe('the pact version no longer exists');
    expect(nobodyUsesSentence(answer)).toBe(
      '5 of 12 operations appear in no pact — including DELETE /invoices/{id} and GET /health. Safe to change, as far as contracts know.',
    );
    expect(evidenceSentence(answer.evidence)).toBe('Unverified — no evidence. no self-verification results were sent');
  });

  it('says when nobody has a pact yet, when every operation is used, and when coverage was not worked out', () => {
    expect(asideHeadline(check({ results: [] }))).toMatchObject({ ring: null, detail: NO_CONSUMERS });
    expect(nobodyUsesSentence(check({ coverage: { operations: 3, used: 3, unused: [], unusedMore: 0 } }))).toBe(
      'Every one of the 3 operations appears in a pact.',
    );
    expect(nobodyUsesSentence(check({ coverage: null, coverageReason: 'operation coverage is worked out for OpenAPI contracts only' }))).toBe(
      'Not worked out: operation coverage is worked out for OpenAPI contracts only.',
    );
  });

  it('reads a conflict and the bytes read from a URL', () => {
    const answer = check({ existing: { contentSha: 'ff', sameContent: false }, summary: { publishable: false }, fetched: { url: 'https://x', bytes: 9, content: 'b3Blbg==' } });
    expect(answer.publishable).toBe(false);
    expect(answer.existingSha).toBe('ff');
    expect(answer.fetched).toEqual({ url: 'https://x', bytes: 9, content: 'b3Blbg==' });
    expect(conflictSentence('2.7.0+9f31c20')).toBe('2.7.0+9f31c20 already has a different contract — use the new commit’s version.');
  });

  it('reads a publish into the dialog’s lines, notifications included', () => {
    const answer = readPublishAnswer({
      published: true,
      created: true,
      contract: {
        provider: { name: 'Billing Service' },
        providerVersion: '2.7.0+9f31c20',
        selfVerification: { status: 'verified', providerContractVerified: true, tool: 'schemathesis', summary: { tests: 412, passed: 412, failed: 0 } },
        comparisons: {
          results: [
            { consumer: 'Orders UI', status: 'compared', verdict: 'fail' },
            { consumer: 'Mobile App', status: 'compared', verdict: 'pass' },
            { consumer: 'Checkout', status: 'already-compared', verdict: 'partial' },
            { consumer: 'Web', status: 'skipped', reason: 'over the limit' },
          ],
        },
      },
    });
    if (!answer.published) throw new Error('expected a publish');
    expect(answer.counts).toEqual({ compatible: 2, incompatible: 1, unverified: 0, notCompared: 1 });
    expect(publishedLines(answer).map((l) => l.text)).toEqual([
      '2 verdicts recorded as compatible',
      '1 recorded as incompatible — Orders UI',
      '1 not compared; see the provider’s comparisons for why',
    ]);
    expect(evidenceSentence(answer.evidence)).toBe('Verified · schemathesis · 412 tests, 0 failed');
    expect(NOTIFICATIONS_LINE).toContain('No webhooks or commit statuses');
    expect(canIDeployHref('Billing Service', '2.7.0+9f31c20')).toBe('/ade/dashboard/pacts/can-i-deploy?pacticipant=Billing+Service&version=2.7.0%2B9f31c20');
  });

  it('reads an unverified publish and a failed run', () => {
    const unverified = readPublishAnswer({
      published: true,
      contract: { selfVerification: { status: 'missing' }, comparisons: { results: [{ consumer: 'A', status: 'compared', verdict: 'unverified' }] } },
    });
    if (!unverified.published) throw new Error('expected a publish');
    expect(unverified.created).toBe(false);
    expect(publishedLines(unverified)[0].text).toContain('1 recorded as unverified: they never unblock a deploy');

    const failed = readPublishAnswer({
      published: false,
      run: { outcome: 'failed', reportId: 'r-1', runId: 'e-1', failing: [{ operation: 'POST /invoices', outcome: 'failed', detail: 'status 500' }], message: 'm' },
    });
    expect(failed).toEqual({
      published: false,
      reportId: 'r-1',
      runId: 'e-1',
      outcome: 'failed',
      failing: [{ operation: 'POST /invoices', outcome: 'failed', detail: 'status 500' }],
      message: 'm',
    });
  });

  it('lists the failed and errored operations of a conformance report', () => {
    expect(
      failingOperations({
        operations: [
          { http_method: 'get', http_path: '/invoices/{id}', outcome: 'passed', drift: [] },
          { http_method: 'post', http_path: '/invoices', outcome: 'failed', drift: [{ message: 'response body: currency is missing' }] },
          { http_method: 'delete', http_path: '/invoices/{id}', outcome: 'errored', drift: [] },
        ],
      }),
    ).toEqual([
      { operation: 'POST /invoices', outcome: 'failed', detail: 'response body: currency is missing' },
      { operation: 'DELETE /invoices/{id}', outcome: 'errored', detail: null },
    ]);
    expect(failingOperations(null)).toEqual([]);
  });
});
