/**
 * The live run's model — PFX-8.9 (#7306): `lib/pact-verify-live.ts` and `lib/pact-verify-upload.ts`.
 *
 * Readers tolerate a partial answer; the drawer's sentences; the log keeps no line twice and at most
 * 2000; the BFF pickers refuse what the drawer and the dialog would not send, naming it; the upload's
 * format guess mirrors the server's Detect and refuses a file no verifier wrote.
 */

import {
  MAX_LOG_LINES,
  clockTime,
  expectedActual,
  failureBadge,
  finishedToast,
  footerNote,
  isRunId,
  mergeLog,
  operationMethod,
  operationPath,
  pactCount,
  pactStatusBadge,
  pickLogAfter,
  pickRerunBody,
  progressPercent,
  readLiveRun,
  reproduceOnMockHref,
  requestText,
  runRestPath,
  runSubtitle,
  type LiveRun,
} from '../lib/pact-verify-live';
import {
  EMPTY_UPLOAD,
  guessFormat,
  pickUpload,
  readUploadAnswer,
  uploadBody,
  uploadCommandAction,
  uploadHeadline,
  uploadProblems,
  type UploadForm,
} from '../lib/pact-verify-upload';

const SHA = 'a'.repeat(64);

const SNAPSHOT = {
  run_id: '6f9c2d1e-0b7a-4c3e-9a51-2f8e7d6c5b4a',
  provider: 'billing-service',
  provider_name: 'Billing Service',
  provider_version: '2.7.0+9f31c20',
  target: 'staging',
  target_base_url: 'https://billing.staging.acme.dev/',
  environment: 'staging',
  status: 'running',
  stop_requested: false,
  started_at: '2026-11-29T14:02:11Z',
  interactions: 61,
  done: 38,
  pacts: [
    {
      consumer: 'orders-ui',
      consumer_name: 'Orders UI',
      consumer_version: '3.4.0',
      pact_version_sha: SHA,
      status: 'failed',
      interactions: 6,
      done: 6,
      passed: 5,
      failed: 1,
    },
    {
      consumer: 'mobile-app',
      consumer_name: 'Mobile App',
      consumer_version: '1.9.2',
      pact_version_sha: 'b'.repeat(64),
      status: 'running',
      interactions: 4,
      done: 2,
    },
  ],
  failure: {
    consumer: 'orders-ui',
    consumer_name: 'Orders UI',
    consumer_version: '3.4.0',
    pact_version_sha: SHA,
    interaction: {
      case_id: 'pact:0',
      description: 'create an invoice',
      operation: 'POST /invoices',
      outcome: 'failed',
      expected_status: '201',
      actual_status: 201,
      provider_states: ['a customer 7 exists'],
      mismatches: [
        {
          attribute: 'body',
          field: '/currency',
          rule: 'regex',
          expected: '^[A-Z]{3}$',
          actual: null,
          description: 'missing',
        },
      ],
    },
  },
  log: [{ seq: 1, kind: 'run', text: '14:02:11 run    4 pact(s)' }],
  log_next: 1,
};

function run(overrides: Record<string, unknown> = {}): LiveRun {
  const read = readLiveRun({ ...SNAPSHOT, ...overrides });
  if (!read) throw new Error('not a run');
  return read;
}

describe('reading a live run', () => {
  it('reads every part the drawer shows, tolerating what is missing', () => {
    const live = run();
    expect(live.pacts).toHaveLength(2);
    expect(live.pacts[1]).toMatchObject({
      consumerName: 'Mobile App',
      status: 'running',
      done: 2,
      interactions: 4,
      passed: 0,
    });
    expect(live.failure?.interaction.mismatches[0]).toMatchObject({
      field: '/currency',
      expected: '^[A-Z]{3}$',
      actual: null,
    });
    expect(live.result).toBeNull();
    expect(live.fault).toBeNull();
    expect(readLiveRun({})).toBeNull();
    expect(readLiveRun({ run_id: 'r' })?.pacts).toEqual([]);
  });

  it('reads a finished run’s answer and a broken run’s fault', () => {
    expect(
      run({ status: 'finished', result: { outcome: 'passed', success: true, target: {} } }).result
        ?.outcome,
    ).toBe('passed');
    expect(run({ status: 'errored', error: { code: 'x', message: 'the run stopped' } }).fault).toBe(
      'the run stopped',
    );
  });
});

describe('what the drawer says', () => {
  it('shows progress and the subtitle', () => {
    expect(progressPercent(run())).toBe(62);
    expect(progressPercent(run({ interactions: 0, done: 0 }))).toBe(0);
    expect(progressPercent(run({ done: 61 }))).toBe(99);
    expect(progressPercent(run({ status: 'finished' }))).toBe(100);
    expect(runSubtitle(run())).toMatch(
      /^Against staging · started \d\d:\d\d:\d\d · 38 of 61 interactions$/,
    );
    expect(clockTime('nope')).toBe('');
  });

  it('labels each pact row', () => {
    const [failed, running] = run().pacts;
    expect(pactStatusBadge(failed)).toEqual({ label: 'Failed', status: 'failed' });
    expect(pactStatusBadge({ ...failed, pending: true }).label).toBe('Failed (pending)');
    expect(pactStatusBadge(running)).toEqual({ label: 'Running', status: 'running' });
    expect(pactStatusBadge({ ...running, status: 'queued' }).label).toBe('Queued');
    expect(pactStatusBadge({ ...running, status: 'stopped' }).label).toBe('Stopped');
    expect(pactCount(failed)).toBe('5 / 6');
    expect(pactCount(running)).toBe('2 / 4');
  });

  it('puts expected beside actual and names the request', () => {
    const live = run();
    const interaction = live.failure!.interaction;
    expect(failureBadge(interaction)).toBe('Body differs');
    expect(expectedActual(interaction)).toEqual({
      expected: ['/currency: ^[A-Z]{3}$  (regex)'],
      actual: ['/currency: (missing)'],
    });
    expect(operationMethod('POST /invoices')).toBe('POST');
    expect(operationPath('POST /invoices')).toBe('/invoices');
    expect(operationPath('Invoice.Get')).toBe('Invoice.Get');
    expect(requestText(live, interaction)).toBe(
      "# provider state: “a customer 7 exists”\ncurl -X POST 'https://billing.staging.acme.dev/invoices'\n# the pact expects status 201",
    );
    const unreachable = { ...interaction, mismatches: [], code: 'timeout', message: 'timed out' };
    expect(failureBadge(unreachable)).toBe('Could not connect');
    expect(expectedActual(unreachable)).toEqual({
      expected: ['status 201'],
      actual: ['timed out'],
    });
  });

  it('says what closing does and how the run ended', () => {
    expect(footerNote(run())).toBe('Closing keeps it running; a toast tells you when it ends.');
    expect(footerNote(run({ stop_requested: true }))).toMatch(/^Stopping/);
    expect(footerNote(run({ status: 'errored', error: { message: 'broke' } }))).toBe('broke');
    const done = (outcome: string, extra: Record<string, unknown> = {}) =>
      finishedToast(
        run({
          status: 'finished',
          result: { outcome, success: outcome === 'passed', target: {}, ...extra },
        }),
      );
    expect(done('passed')).toMatchObject({ title: 'Verification passed', tone: 'success' });
    expect(done('failed').tone).toBe('error');
    expect(done('stopped').title).toBe('Verification stopped');
    expect(
      done('could-not-connect', { connection_error: 'Could not connect to x (timeout)' }),
    ).toMatchObject({
      title: 'Could not connect',
      description: 'Could not connect to x (timeout)',
    });
    expect(finishedToast(run({ status: 'errored', error: { message: 'broke' } })).title).toBe(
      'The verification run broke',
    );
  });

  it('reproduces on the provider’s project mock, or says it cannot', () => {
    expect(reproduceOnMockHref('p 1')).toBe('/ade/dashboard/versions?projectId=p%201');
    expect(reproduceOnMockHref(null)).toBeNull();
  });
});

describe('the log', () => {
  it('appends only new lines and keeps the newest 2000', () => {
    const line = (seq: number) => ({
      seq,
      kind: 'interaction',
      outcome: null,
      text: `line ${seq}`,
    });
    expect(mergeLog([line(1), line(2)], [line(2), line(3)]).map((l) => l.seq)).toEqual([1, 2, 3]);
    const many = Array.from({ length: MAX_LOG_LINES }, (_v, i) => line(i + 1));
    const merged = mergeLog(many, [line(MAX_LOG_LINES + 1)]);
    expect(merged).toHaveLength(MAX_LOG_LINES);
    expect(merged[0].seq).toBe(2);
  });
});

describe('the run BFF pickers', () => {
  it('accepts a run id and the log cursor only', () => {
    expect(isRunId(SNAPSHOT.run_id)).toBe(true);
    expect(isRunId('../etc')).toBe(false);
    expect(runRestPath(SNAPSHOT.run_id, 'stop')).toBe(`pact-verifier/runs/${SNAPSHOT.run_id}/stop`);
    expect(pickLogAfter(new URLSearchParams('log_after=12'))).toEqual({ ok: true, logAfter: 12 });
    expect(pickLogAfter(new URLSearchParams(''))).toEqual({ ok: true, logAfter: 0 });
    expect(pickLogAfter(new URLSearchParams('log_after=-1'))).toEqual({
      ok: false,
      error: 'log_after must be a whole number.',
    });
    expect(pickLogAfter(new URLSearchParams('tenant=other'))).toEqual({
      ok: false,
      error: 'tenant is not a parameter of a run read.',
    });
  });

  it('accepts a re-run of one interaction and nothing else', () => {
    expect(pickRerunBody({ pact_version_sha: SHA, case_id: 'pact:0' })).toEqual({
      ok: true,
      body: { pact_version_sha: SHA, case_id: 'pact:0' },
    });
    expect(pickRerunBody({ pact_version_sha: SHA, case_id: 'pact:0', publish: true })).toEqual({
      ok: false,
      error: 'publish is not a field of a re-run.',
    });
    expect(pickRerunBody({ pact_version_sha: 'zz', case_id: 'c' })).toMatchObject({ ok: false });
    expect(pickRerunBody({ pact_version_sha: SHA, case_id: '' })).toMatchObject({ ok: false });
    expect(pickRerunBody([])).toMatchObject({ ok: false });
  });
});

// --- the upload -------------------------------------------------------------------------------------

const FORM: UploadForm = {
  ...EMPTY_UPLOAD,
  consumer: 'orders-ui',
  sha: SHA,
  providerVersion: '2.7.0+9f31c20',
  file: { name: 'report.json', text: '{"result": true}' },
};

describe('guessing the report format', () => {
  it.each([
    [
      'r.xml',
      '<testsuites><testsuite name="schemathesis"></testsuite></testsuites>',
      'schemathesis',
    ],
    ['r.xml', '<?xml version="1.0"?>\n<testsuite name="Dredd Tests"></testsuite>', 'dredd'],
    ['r.xml', '<testsuite name="jest"><testcase name="a"/></testsuite>', 'junit'],
    ['r.json', '{"collection": {}, "run": {"executions": []}}', 'newman'],
    ['r.json', '{"result": false, "errors": []}', 'pact-verifier-json'],
    [
      'r.ndjson',
      '{"Initialize": {"schemathesis_version": "4.3"}}\n{"EngineFinished": {}}',
      'schemathesis',
    ],
  ])('reads %s as the server would', (name, text, format) => {
    expect(guessFormat(name, text).format).toBe(format);
  });

  it.each([
    ['r.txt', 'TAP version 13', 'neither JSON nor XML'],
    ['r.json', '', 'empty'],
    ['r.json', '{"a": ', 'not valid JSON'],
    ['r.ndjson', '{"a": 1}\n{"b": 2}', 'not a Schemathesis report'],
  ])('refuses %s with the reason', (name, text, reason) => {
    const guess = guessFormat(name, text);
    expect(guess.format).toBeNull();
    expect(guess.sentence).toContain(reason);
  });
});

describe('the upload form', () => {
  it('names every missing or malformed field', () => {
    expect(uploadProblems(FORM)).toEqual([]);
    const fields = uploadProblems({ ...EMPTY_UPLOAD, buildUrl: 'ftp://x' }).map((p) => p.field);
    expect(fields).toEqual(['consumer', 'sha', 'providerVersion', 'buildUrl', 'file']);
    expect(uploadProblems({ ...FORM, sha: 'abc' })[0].message).toContain('64-character');
    expect(
      uploadProblems({ ...FORM, file: { name: 'r.txt', text: 'hello' } })[0].message,
    ).toContain('nothing is recorded');
  });

  it('sends the report with its media type and only the options set', () => {
    expect(
      uploadBody('billing-service', { ...FORM, tags: 'rc, staging', format: 'dredd' }),
    ).toEqual({
      provider: 'billing-service',
      consumer: 'orders-ui',
      pact_version_sha: SHA,
      provider_version: '2.7.0+9f31c20',
      format: 'dredd',
      report: '{"result": true}',
      content_type: 'application/json',
      tags: ['rc', 'staging'],
    });
  });

  it('is the same as apiome pact publish-verification-results and the REST call', () => {
    const action = uploadCommandAction(
      'Billing Service',
      { ...FORM, branch: 'main', format: 'newman' },
      'acme',
    );
    expect(action.verb).toBe('publish-verification-results');
    expect(action.args).toEqual([{ value: 'report.json' }]);
    expect(action.options?.find((o) => o.flag === '--format')?.value).toBe('newman');
    expect(action.rest.path).toBe(
      `/v1/tenants/acme/pact-broker/pacts/provider/Billing%20Service/consumer/orders-ui/pact-version/${SHA}/external-verification-results?providerApplicationVersion=2.7.0%2B9f31c20&branch=main&format=newman`,
    );
    expect(
      uploadCommandAction('p', { ...FORM, format: 'auto' }, '').options?.find(
        (o) => o.flag === '--format',
      )?.value,
    ).toBe('');
  });

  it('reads what the server stored and says it in one line', () => {
    const answer = readUploadAnswer({
      success: false,
      ingestion: {
        format: 'dredd',
        interactions: 1,
        notices: [{ pointer: '//testcase[1]', reason: 'kept' }],
      },
      _links: { self: { href: 'https://x/verification-results/2' } },
    });
    expect(answer).toEqual({
      success: false,
      format: 'dredd',
      interactions: 1,
      notices: [{ pointer: '//testcase[1]', reason: 'kept' }],
      resultUrl: 'https://x/verification-results/2',
    });
    expect(uploadHeadline(answer)).toBe(
      'Recorded a failed result from a Dredd report: 1 interaction, 1 note.',
    );
  });
});

describe('the upload BFF picker', () => {
  const body = uploadBody('billing-service', { ...FORM, buildUrl: 'https://ci/1', tags: 'rc' });

  it('builds the REST call below the tenant', () => {
    const picked = pickUpload(body);
    expect(picked.ok && picked.upload).toEqual({
      path: `pact-broker/pacts/provider/billing-service/consumer/orders-ui/pact-version/${SHA}/external-verification-results?providerApplicationVersion=2.7.0%2B9f31c20&buildUrl=https%3A%2F%2Fci%2F1&tag=rc`,
      report: '{"result": true}',
      contentType: 'application/json',
    });
  });

  it.each([
    [{ ...body, tenant: 'other' }, 'tenant is not a field of an upload.'],
    [{ ...body, provider: '' }, 'provider is required.'],
    [{ ...body, consumer: '../x' }, 'provider and consumer must be pacticipant names.'],
    [
      { ...body, pact_version_sha: 'abc' },
      'pact_version_sha must be the pact version (64 hex characters).',
    ],
    [
      { ...body, format: 'tap' },
      'format must be one of auto, pact-verifier-json, junit, schemathesis, newman, dredd.',
    ],
    [{ ...body, tags: 'rc' }, 'tags must be at most 20 names.'],
    [{ ...body, report: '' }, 'report is required: the report’s text.'],
    [{ ...body, content_type: 'text/html' }, 'content_type must be the media type of a report.'],
    [{ ...body, provider_version: 1 }, 'provider_version must be text of at most 255 characters.'],
    [null, 'The request must be a JSON object.'],
  ])('refuses %j', (raw, error) => {
    expect(pickUpload(raw)).toEqual({ ok: false, error });
  });
});
