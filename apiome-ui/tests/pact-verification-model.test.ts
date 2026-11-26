/**
 * @jest-environment node
 */
/**
 * Verification results and operations — PFX-5.5 (#6949): the model and the `/api/pact` proxies.
 *
 * * **Routes and paths**: the page and result routes, the REST paths the proxies forward to.
 * * **History query**: `consumer` a handle, `cursor` a position; anything else refused by name.
 * * **Run body**: only the known fields, each the right type and size; `target_ref` always and
 *   `provider_version` for verify-all-stale required; an unsafe build URL refused.
 * * **Wording**: trigger labels (a result before triggers were recorded reads *Not recorded*),
 *   durations, pass rate, verdicts, the run sentence.
 * * **Expected vs actual**: every `testResults` entry read in order; a mismatch's expected and
 *   actual kept (also falsy values); an entry the page cannot read kept as JSON.
 * * **Log**: deterministic text with every interaction, mismatch and evidence request; a missing
 *   evidence run says why; the download's file name.
 * * **Proxies**: forward as the signed-in user in the session tenant; refuse bad input without
 *   calling REST; keep REST's refusal.
 */

import { jest } from '@jest/globals';
import { NextRequest, NextResponse } from 'next/server';

let tenant: { user: { user_id: string }; slug: string } | { error: NextResponse } = {
  user: { user_id: 'u-1' },
  slug: 'acme',
};
const forwarded: Array<{ url: string; method: string; body?: unknown }> = [];
let restAnswer: { status: number; body: unknown } = { status: 200, body: { ok: true } };

jest.mock('@lib/connectors-proxy', () => ({
  resolveConnectorTenant: async () => tenant,
  tenantUrl: (slug: string, path: string) => `http://rest/v1/tenants/${slug}/${path}`,
  forwardConnectorRequest: async (url: string, init: { method: string; body?: unknown }) => {
    forwarded.push({ url, method: init.method, body: init.body });
    return restAnswer.status < 400
      ? NextResponse.json(restAnswer.body)
      : NextResponse.json({ success: false, error: 'Permission denied' }, { status: restAnswer.status });
  },
}));

jest.mock('@lib/rest-auth', () => ({
  createRestAuthHeaders: () => ({ Authorization: 'Bearer session' }),
  REST_API_BASE_URL: 'http://rest/v1',
}));

import {
  EVIDENCE_TEXT,
  formatDuration,
  historyQueryProblem,
  interactionOutcomes,
  isPactSha,
  isResultId,
  logFileName,
  passRate,
  pickRunBody,
  renderVerificationLog,
  resultProxyPath,
  resultVerdict,
  reverifyProxyPath,
  runSummary,
  statusProxyPath,
  targetOptions,
  triggerLabel,
  verificationResultRoute,
  verificationRoute,
  verifyStaleProxyPath,
  type ConsoleRunResponse,
  type ResultDetail,
} from '../lib/pact-verification';
import { GET as statusGet } from '../src/app/api/pact/pacticipants/[pacticipant]/verification/status/route';
import { GET as resultsGet } from '../src/app/api/pact/pacticipants/[pacticipant]/verification/results/route';
import { GET as resultGet } from '../src/app/api/pact/pacticipants/[pacticipant]/verification/results/[resultId]/route';
import { POST as reverifyPost } from '../src/app/api/pact/pacticipants/[pacticipant]/verification/reverify/route';
import { POST as verifyStalePost } from '../src/app/api/pact/pacticipants/[pacticipant]/verification/verify-stale/route';
import fixture from './fixtures/pact-verification.json';

const DETAIL = fixture.detail as unknown as ResultDetail;
const RESULT_ID = DETAIL.result.id;
const SHA = DETAIL.result.pact_version_sha;

describe('routes and REST paths', () => {
  it('builds the page and result routes', () => {
    expect(verificationRoute('ledger-api')).toBe('/ade/dashboard/pacts/pacticipants/ledger-api/verification');
    expect(verificationRoute('ledger-api', 'billing-service')).toBe(
      '/ade/dashboard/pacts/pacticipants/ledger-api/verification?consumer=billing-service',
    );
    expect(verificationResultRoute('ledger-api', RESULT_ID)).toBe(
      `/ade/dashboard/pacts/pacticipants/ledger-api/verification/results/${RESULT_ID}`,
    );
  });

  it('builds the REST paths below the tenant', () => {
    expect(statusProxyPath('ledger-api')).toBe('pact-verifier/pacts/provider/ledger-api/verification-status');
    expect(resultProxyPath('ledger-api', RESULT_ID)).toBe(`pact-verifier/pacts/provider/ledger-api/results/${RESULT_ID}`);
    expect(reverifyProxyPath('ledger-api', 'billing-service', SHA.toUpperCase())).toBe(
      `pact-verifier/pacts/provider/ledger-api/consumer/billing-service/pact-version/${SHA}/reverify`,
    );
    expect(verifyStaleProxyPath('ledger-api')).toBe('pact-verifier/pacts/provider/ledger-api/verify-stale');
  });

  it('tells result ids and pact versions apart from anything else', () => {
    expect(isResultId(RESULT_ID)).toBe(true);
    expect(isResultId('1')).toBe(false);
    expect(isResultId(`${RESULT_ID}/x`)).toBe(false);
    expect(isPactSha(SHA)).toBe(true);
    expect(isPactSha(SHA.slice(1))).toBe(false);
    expect(isPactSha(`${SHA.slice(1)}g`)).toBe(false);
  });
});

describe('the history query', () => {
  it.each([
    ['', null],
    ['consumer=billing-service', null],
    ['cursor=118', null],
    ['consumer=Billing%20Service', 'The consumer filter is not a pacticipant handle.'],
    ['cursor=abc', 'The cursor is not valid.'],
    ['cursor=12345678901234567890', 'The cursor is not valid.'],
  ])('%s → %s', (query, problem) => {
    expect(historyQueryProblem(new URLSearchParams(query))).toBe(problem);
  });
});

describe('the run body', () => {
  it('keeps the known fields, trimmed', () => {
    expect(
      pickRunBody(
        {
          target_ref: ' ledger-staging ',
          provider_version: '4f1e2d0',
          provider_branch: '',
          build_url: 'https://ci.example.com/1',
          verification: { allow_mutating: true },
        },
        true,
      ),
    ).toEqual({
      ok: true,
      body: {
        target_ref: 'ledger-staging',
        provider_version: '4f1e2d0',
        build_url: 'https://ci.example.com/1',
        verification: { allow_mutating: true },
      },
    });
  });

  it.each([
    [null, false, 'The body must be a JSON object.'],
    [[], false, 'The body must be a JSON object.'],
    [{}, false, 'Choose a verification target (target_ref).'],
    [{ target_ref: 't', publish: false }, false, 'Unsupported field publish: a run accepts target_ref, provider_version, provider_branch, build_url, verification.'],
    [{ target_ref: 7 }, false, 'target_ref must be text.'],
    [{ target_ref: 'x'.repeat(201) }, false, 'target_ref is longer than 200 characters.'],
    [{ target_ref: 't' }, true, 'Give the provider version the pacts are verified as (provider_version).'],
    [{ target_ref: 't', build_url: 'javascript:alert(1)' }, false, 'build_url must be an http(s) URL.'],
    [{ target_ref: 't', verification: [] }, false, 'verification must be an object.'],
    [{ target_ref: 't', verification: { fixtures: {} } }, false, 'Unsupported option verification.fixtures: a run accepts allow_mutating, replay_without_state_setup.'],
    [{ target_ref: 't', verification: { allow_mutating: 'yes' } }, false, 'verification.allow_mutating must be true or false.'],
  ])('refuses %j (version required: %s)', (raw, requireVersion, error) => {
    expect(pickRunBody(raw, requireVersion)).toEqual({ ok: false, error });
  });
});

describe('wording', () => {
  it('names every trigger, and an unrecorded one', () => {
    expect(triggerLabel('published')).toBe('Pact verifier');
    expect(triggerLabel('hosted')).toBe('Hosted verifier');
    expect(triggerLabel('manual')).toBe('Re-run');
    expect(triggerLabel('stale-recheck')).toBe('Stale re-check');
    expect(triggerLabel('bidirectional')).toBe('Bi-directional');
    expect(triggerLabel(null)).toBe('Not recorded');
    expect(triggerLabel('nightly')).toBe('nightly');
  });

  it.each([
    [null, '—'],
    [-1, '—'],
    [420, '420 ms'],
    [1840, '1.8 s'],
    [60_000, '1 min'],
    [125_000, '2 min 5 s'],
  ])('formats %s ms as %s', (ms, text) => {
    expect(formatDuration(ms)).toBe(text);
  });

  it('gives the pass rate and the verdicts', () => {
    expect(passRate(fixture.status.counts)).toBe('86%');
    expect(passRate({ ...fixture.status.counts, interactions: 0 })).toBe('—');
    expect(resultVerdict({ success: true, pending: null })).toEqual({ label: 'Passed', variant: 'success' });
    expect(resultVerdict({ success: false, pending: true })).toEqual({ label: 'Failed (pending)', variant: 'warn' });
    expect(resultVerdict({ success: false, pending: false })).toEqual({ label: 'Failed', variant: 'danger' });
  });

  it('sums a run up, including what it did not run', () => {
    const run = fixture.run as unknown as ConsoleRunResponse;
    expect(runSummary(run)).toBe('1 pact verified as 4f1e2d0: 1 passed.');
    expect(
      runSummary({
        ...run,
        pacts: [...run.pacts, { ...run.pacts[0], outcome: 'failed', pact_version_sha: 'b' }],
        skipped: [{ ...run.pacts[0], code: 'pact-verify-in-progress', reason: 'already running' }],
      }),
    ).toBe('2 pacts verified as 4f1e2d0: 1 passed, 1 failed. 1 not run.');
    expect(runSummary({ ...run, pacts: [], skipped: [] })).toBe('No stale pact: nothing to verify.');
    expect(
      runSummary({ ...run, pacts: [], skipped: [{ ...run.pacts[0], code: 'x', reason: 'y' }] }),
    ).toBe('No pact was verified. 1 not run.');
  });

  it('lists the targets enabled first, by name, and survives a bad body', () => {
    expect(targetOptions(fixture.targets).map((t) => [t.slug, t.enabled])).toEqual([
      ['ledger-staging', true],
      ['ledger-old', false],
    ]);
    expect(targetOptions({})).toEqual([]);
    expect(targetOptions(null)).toEqual([]);
  });
});

describe('expected vs actual', () => {
  it('reads every interaction in order with its mismatches', () => {
    const outcomes = interactionOutcomes(DETAIL.test_results);
    expect(outcomes.map((o) => [o.description, o.success])).toEqual([
      ['a request for invoice 1042', true],
      ['a request for the yearly summary', false],
      ['a request to create an invoice', true],
    ]);
    expect(outcomes[0].providerState).toBe('an invoice 1042 exists');
    expect(outcomes[1].code).toBe('pact-body-mismatch');
    expect(outcomes[1].mismatches[0]).toEqual({
      attribute: 'body',
      field: '/year',
      rule: 'type',
      description: 'expected a number but was a string',
      expected: '2026',
      actual: '"2026"',
    });
  });

  it('keeps falsy values, absent values and exceptions, and an entry it cannot read', () => {
    const outcomes = interactionOutcomes([
      { description: 'x', success: false, mismatches: [{ attribute: 'body', path: '/a', expected: 0, actual: null }] },
      { interactionDescription: 'y', success: false, mismatches: [{ attribute: 'status', description: 'expected 200 but was 404' }] },
      { interactionDescription: 'z', success: false, outcome: 'skipped', exceptions: [{ message: 'provider state not set up' }, 'plain'] },
      'garbage',
      { success: true },
    ]);
    expect(outcomes[0].mismatches[0]).toMatchObject({ field: '/a', expected: '0', actual: 'null' });
    expect(outcomes[1].mismatches[0]).toMatchObject({ expected: null, actual: null, description: 'expected 200 but was 404' });
    expect(outcomes[2]).toMatchObject({ outcome: 'skipped', messages: ['provider state not set up', 'plain'] });
    expect(outcomes[3]).toMatchObject({ description: 'Entry 4', success: false, unreadable: '"garbage"' });
    expect(outcomes[4].description).toBe('Interaction 5');
  });
});

describe('the log', () => {
  it('is the whole result as text, the same every time', () => {
    const log = renderVerificationLog(DETAIL);
    expect(log).toBe(renderVerificationLog(DETAIL));
    expect(log).toContain('Verification result 3 — Billing Service → Ledger API');
    expect(log).toContain('Provider version: 4f1e2d0 (branch main)');
    expect(log).toContain('Trigger:          Re-run');
    expect(log).toContain('Duration:         1.8 s');
    expect(log).toContain('[PASS] a request for invoice 1042');
    expect(log).toContain('[FAILED] a request for the yearly summary');
    expect(log).toContain('  Mismatch at body /year (rule type)');
    expect(log).toContain('    Expected: 2026');
    expect(log).toContain('    Actual:   "2026"');
    expect(log).toContain('Evidence run 0b6f3c1e-8a2d-4e5f-9a1b-2c3d4e5f6a7b');
    expect(log).toContain('GET /summary → 200 (expected 200) · failed · 688 ms');
    expect(log).toContain('POST /invoices → 201 (expected 201) · passed · 540 ms · 2 attempts');
    expect(log).toContain('  - failed body /entries/0/balance');
    expect(log.endsWith('\n')).toBe(true);
  });

  it.each(['not-recorded', 'not-found', 'forbidden'] as const)('says why the evidence is absent (%s)', (status) => {
    const log = renderVerificationLog({ ...DETAIL, evidence: null, evidence_status: status });
    expect(log).toContain(EVIDENCE_TEXT[status]);
    expect(log).not.toContain('Evidence run');
  });

  it('names the download after the pair, the pact and the number', () => {
    expect(logFileName(DETAIL)).toBe(`verification-ledger-api-billing-service-${SHA.slice(0, 12)}-3.log`);
  });
});

describe('the /api/pact verification proxies', () => {
  const ctx = (params: Record<string, string>) => ({ params: Promise.resolve(params) }) as never;
  const req = (path: string, init?: { method: string; body?: string }) =>
    new NextRequest(`http://ui${path}`, init as never);
  const base = '/api/pact/pacticipants/ledger-api/verification';

  beforeEach(() => {
    tenant = { user: { user_id: 'u-1' }, slug: 'acme' };
    forwarded.length = 0;
    restAnswer = { status: 200, body: { ok: true } };
  });

  it('forwards the status and one result as the signed-in user in the session tenant', async () => {
    expect((await statusGet(req(`${base}/status`), ctx({ pacticipant: 'ledger-api' }))).status).toBe(200);
    expect(
      (await resultGet(req(`${base}/results/${RESULT_ID}`), ctx({ pacticipant: 'ledger-api', resultId: RESULT_ID })))
        .status,
    ).toBe(200);
    expect(forwarded.map((call) => [call.method, call.url])).toEqual([
      ['GET', 'http://rest/v1/tenants/acme/pact-verifier/pacts/provider/ledger-api/verification-status'],
      ['GET', `http://rest/v1/tenants/acme/pact-verifier/pacts/provider/ledger-api/results/${RESULT_ID}`],
    ]);
  });

  it('forwards the history with its filters and page size', async () => {
    await resultsGet(req(`${base}/results?consumer=billing-service&cursor=118`), ctx({ pacticipant: 'ledger-api' }));
    expect(forwarded[0].url).toBe(
      'http://rest/v1/tenants/acme/pact-verifier/pacts/provider/ledger-api/results?limit=25&consumer=billing-service&cursor=118',
    );
  });

  it('refuses bad reads without calling REST', async () => {
    const answers = [
      await statusGet(req(`${base}/status?x=1`), ctx({ pacticipant: 'ledger-api' })),
      await statusGet(req('/api/pact/pacticipants/Bad%20Name/verification/status'), ctx({ pacticipant: 'Bad Name' })),
      await resultsGet(req(`${base}/results?cursor=abc`), ctx({ pacticipant: 'ledger-api' })),
      await resultsGet(req(`${base}/results?label=x`), ctx({ pacticipant: 'ledger-api' })),
      await resultsGet(req(`${base}/results?consumer=a&consumer=b`), ctx({ pacticipant: 'ledger-api' })),
      await resultGet(req(`${base}/results/7`), ctx({ pacticipant: 'ledger-api', resultId: '7' })),
    ];
    expect(answers.map((answer) => answer.status)).toEqual([400, 404, 400, 400, 400, 404]);
    expect(((await answers[3].json()) as { error: string }).error).toContain('Unsupported parameter label');
    expect(forwarded).toHaveLength(0);
  });

  it('forwards a checked re-run body as a POST', async () => {
    const answer = await reverifyPost(
      req(`${base}/reverify?consumer=billing-service&sha=${SHA}`, {
        method: 'POST',
        body: JSON.stringify({ target_ref: 'ledger-staging' }),
      }),
      ctx({ pacticipant: 'ledger-api' }),
    );
    expect(answer.status).toBe(200);
    expect(forwarded).toEqual([
      {
        method: 'POST',
        url: `http://rest/v1/tenants/acme/pact-verifier/pacts/provider/ledger-api/consumer/billing-service/pact-version/${SHA}/reverify`,
        body: { target_ref: 'ledger-staging' },
      },
    ]);
  });

  it.each([
    [`?consumer=billing-service`, { target_ref: 't' }, 'The sha parameter is not a pact version (64 hex characters).'],
    [`?sha=${SHA}`, { target_ref: 't' }, 'The consumer parameter is not a pacticipant handle.'],
    [`?consumer=billing-service&sha=${SHA}&x=1`, { target_ref: 't' }, 'Unsupported parameter x: a re-run accepts consumer, sha.'],
    [`?consumer=billing-service&consumer=b&sha=${SHA}`, { target_ref: 't' }, 'The consumer parameter is given more than once.'],
    [`?consumer=billing-service&sha=${SHA}`, { target_ref: 't', publish: false }, 'Unsupported field publish: a run accepts target_ref, provider_version, provider_branch, build_url, verification.'],
  ])('refuses a re-run %s %j without calling REST', async (query, body, error) => {
    const answer = await reverifyPost(
      req(`${base}/reverify${query}`, { method: 'POST', body: JSON.stringify(body) }),
      ctx({ pacticipant: 'ledger-api' }),
    );
    expect(answer.status).toBe(400);
    expect(await answer.json()).toEqual({ success: false, error });
    expect(forwarded).toHaveLength(0);
  });

  it('requires a provider version for verify-all-stale and forwards a good body', async () => {
    const missing = await verifyStalePost(
      req(`${base}/verify-stale`, { method: 'POST', body: JSON.stringify({ target_ref: 't' }) }),
      ctx({ pacticipant: 'ledger-api' }),
    );
    expect(missing.status).toBe(400);
    const notJson = await verifyStalePost(
      req(`${base}/verify-stale`, { method: 'POST', body: 'nope' }),
      ctx({ pacticipant: 'ledger-api' }),
    );
    expect(notJson.status).toBe(400);
    expect(forwarded).toHaveLength(0);
    const ok = await verifyStalePost(
      req(`${base}/verify-stale`, {
        method: 'POST',
        body: JSON.stringify({ target_ref: 't', provider_version: '4f1e2d0' }),
      }),
      ctx({ pacticipant: 'ledger-api' }),
    );
    expect(ok.status).toBe(200);
    expect(forwarded[0]).toMatchObject({ method: 'POST', body: { target_ref: 't', provider_version: '4f1e2d0' } });
  });

  it('keeps REST’s refusal and the session’s own', async () => {
    restAnswer = { status: 403, body: {} };
    const refused = await statusGet(req(`${base}/status`), ctx({ pacticipant: 'ledger-api' }));
    expect(refused.status).toBe(403);
    tenant = { error: NextResponse.json({ success: false, error: 'Unauthorized' }, { status: 401 }) };
    const anonymous = await verifyStalePost(
      req(`${base}/verify-stale`, { method: 'POST', body: JSON.stringify({ target_ref: 't', provider_version: '1' }) }),
      ctx({ pacticipant: 'ledger-api' }),
    );
    expect(anonymous.status).toBe(401);
    expect(forwarded).toHaveLength(1);
  });
});
