/**
 * The pre-publish check's model — PFX-8.4 (#7301): the proxy's body, the choices, reading REST's
 * answer, the pills, the drawer and the command.
 */

import {
  MAX_SELECTORS,
  checkCommandAction,
  compareChoices,
  defaultSelectors,
  differenceView,
  interactionNote,
  nothingToCompare,
  orderedInteractions,
  parseSelector,
  pickCompareBody,
  pillCount,
  pillLabel,
  readCompareAnswer,
  type CheckInteraction,
  type CheckResult,
} from '../lib/pact-publish-check';
import { MAX_PACT_CHARS } from '../lib/pact-publish';
import { pactCommandSurfaces } from '../lib/pact-commands';

const PACT = { consumer: { name: 'Orders UI' }, provider: { name: 'Billing Service' }, interactions: [] };

/** REST's answer with two provider versions. */
function answer() {
  return {
    consumer: { name: 'Orders UI' },
    provider: { name: 'Billing Service', slug: 'billing-service', registered: true },
    summary: { success: false },
    results: [
      {
        selectors: ['main'],
        reasons: ['main branch main'],
        providerVersion: '2.7.0',
        draft: false,
        verdict: 'fail',
        success: false,
        source: { projectId: 'p-1', projectSlug: 'billing-api', versionLabel: '2.7.0' },
        counts: { match: 1, differs: 1, notInSpec: 1 },
        interactions: [
          { index: 0, method: 'GET', path: '/invoices/1', status: 200, providerStates: ['an invoice exists'], outcome: 'match', failures: [] },
          {
            index: 1,
            method: 'POST',
            path: '/invoices',
            status: 201,
            outcome: 'differs',
            failures: [
              { code: 'response.body.unknown-property', message: 'currency is not declared', pactPointer: '/interactions/1/response/body/currency' },
              { code: 'response.body.schema-mismatch', message: 'amount is not an integer' },
            ],
            expected: { value: { status: 201, body: { currency: 'EUR' } } },
            declared: { pointer: '#/paths/~1invoices/post/responses/201', value: { description: 'Created' } },
          },
          { index: 2, method: 'GET', path: '/invoices/1/pdf', status: 200, outcome: 'not-in-spec', failures: [{ code: 'request.operation.unknown', message: 'no operation' }] },
        ],
      },
      { selectors: ['deployed:production'], reasons: ['deployed to production'], providerVersion: '2.6.1', counts: { match: 3 }, interactions: [] },
    ],
    unresolved: [{ selector: 'deployed:staging', reason: 'nothing deployed' }],
    skipped: [],
  };
}

describe('pickCompareBody', () => {
  it('takes exactly a pact and its selectors', () => {
    expect(pickCompareBody({ pact: PACT, against: ['main'] })).toEqual({ ok: true, body: { pact: PACT, against: ['main'] } });
  });

  it.each([
    [null, 'JSON object'],
    [{ pact: PACT, against: ['main'], merge: true }, 'Unsupported field merge'],
    [{ against: ['main'] }, 'pact must be'],
    [{ pact: PACT, against: [] }, `1 to ${MAX_SELECTORS}`],
    [{ pact: PACT, against: Array(MAX_SELECTORS + 1).fill('main') }, `1 to ${MAX_SELECTORS}`],
    [{ pact: PACT, against: [3] }, 'text of at most'],
    [{ pact: PACT, against: ['x'.repeat(301)] }, 'text of at most'],
    [{ pact: { blob: 'x'.repeat(MAX_PACT_CHARS) }, against: ['main'] }, 'too large'],
  ])('refuses %j', (raw, words) => {
    const picked = pickCompareBody(raw);
    expect(picked.ok).toBe(false);
    if (!picked.ok) expect(picked.error).toContain(words);
  });
});

describe('the choices', () => {
  it('offers main, each environment and the latest draft', () => {
    expect(compareChoices(['production', 'staging']).map((c) => [c.selector, c.label])).toEqual([
      ['main', 'Provider’s main'],
      ['deployed:production', 'Deployed to production'],
      ['deployed:staging', 'Deployed to staging'],
      ['draft:latest', 'Draft · latest'],
    ]);
  });

  it('starts with main and the production environment', () => {
    expect(defaultSelectors([{ name: 'staging', production: false }, { name: 'prod', production: true }])).toEqual(['main', 'deployed:prod']);
    expect(defaultSelectors([{ name: 'qa', production: false }])).toEqual(['main', 'deployed:qa']);
    expect(defaultSelectors([])).toEqual(['main']);
  });

  it.each([
    ['2.7.0', 'version:2.7.0'],
    ['main', 'main'],
    ['deployed:staging', 'deployed:staging'],
    ['Draft: 2.8.0-rc1', 'draft:2.8.0-rc1'],
    ['version:3', 'version:3'],
  ])('reads %s as %s', (typed, selector) => {
    expect(parseSelector(typed)).toMatchObject({ selector });
  });

  it.each([[''], ['deployed:'], ['tag:prod'], ['x'.repeat(301)]])('refuses %j with a reason', (typed) => {
    expect(parseSelector(typed)).toHaveProperty('error');
  });
});

describe('the answer', () => {
  it('reads REST’s answer, pills and counts', () => {
    const read = readCompareAnswer(answer())!;
    expect(read.provider).toBe('Billing Service');
    expect(read.results.map(pillLabel)).toEqual(['main · 2.7.0', 'production · 2.6.1']);
    expect(pillCount(read.results[0])).toBe('1/3');
    expect(read.unresolved).toEqual([{ selector: 'deployed:staging', reason: 'nothing deployed' }]);
    expect(nothingToCompare(read)).toBeNull();
  });

  it('labels a draft and a named version', () => {
    const base = readCompareAnswer(answer())!.results[0];
    expect(pillLabel({ ...base, draft: true, providerVersion: '2.8.0-rc1', selectors: ['draft:latest'] })).toBe('draft · 2.8.0-rc1');
    expect(pillLabel({ ...base, selectors: ['version:2.7.0'] })).toBe('2.7.0');
  });

  it('is not an answer without a provider', () => {
    expect(readCompareAnswer({ results: [] })).toBeNull();
    expect(readCompareAnswer('nope')).toBeNull();
  });

  it('says so when nothing could be compared', () => {
    const read = readCompareAnswer({ ...answer(), results: [] })!;
    expect(nothingToCompare(read)).toBe(
      'Billing Service has no contract or deployed version yet. Publish anyway — the verdict appears when the provider shows up.',
    );
  });

  it('lists what differs first, then what is not in the spec, then matches', () => {
    const rows = readCompareAnswer(answer())!.results[0].interactions;
    expect(orderedInteractions(rows).map((row) => row.outcome)).toEqual(['differs', 'not-in-spec', 'match']);
    expect(rows.map((row) => row.outcome)).toEqual(['match', 'differs', 'not-in-spec']);
  });

  it('writes the line under each interaction', () => {
    const [match, differs, missing] = readCompareAnswer(answer())!.results[0].interactions;
    expect(interactionNote(match, '2.7.0')).toBe('“an invoice exists” · 200');
    expect(interactionNote(differs, '2.7.0')).toBe('currency is not declared (+1 more)');
    expect(interactionNote(missing, '2.7.0')).toBe('Not in the spec of 2.7.0. The provider may serve it undocumented.');
  });
});

describe('the drawer', () => {
  const result = readCompareAnswer(answer())!.results[0] as CheckResult;
  const differs = result.interactions[1] as CheckInteraction;

  it('shows the pact beside the spec, the findings and the spec change', () => {
    const view = differenceView(differs, result, 'Billing Service');
    expect(view.title).toBe('POST /invoices — 201');
    expect(view.subtitle).toBe('What the pact needs, beside what Billing Service 2.7.0 declares');
    expect(JSON.parse(view.expected)).toEqual({ status: 201, body: { currency: 'EUR' } });
    expect(JSON.parse(view.declared)).toEqual({ description: 'Created' });
    expect(view.declaredPointer).toBe('#/paths/~1invoices/post/responses/201');
    expect(view.findings).toHaveLength(2);
    expect(view.specChangeHref).toBe('/ade/dashboard/versions?projectId=p-1');
    expect(view.specChangeLabel).toBe('Open billing-api 2.7.0');
  });

  it('says why when there is nothing to show', () => {
    const view = differenceView({ ...differs, expected: { truncated: true, bytes: 9000 }, declared: undefined }, { ...result, source: null }, 'B');
    expect(view.expected).toBe('Too large to show here (9000 bytes).');
    expect(view.declared).toBe('No declaration was sent.');
    expect(view.specChangeHref).toBeNull();
    const missing = differenceView(result.interactions[2], result, 'B');
    expect(missing.declared).toBe('The spec declares no such operation.');
  });
});

describe('the command', () => {
  it('is apiome pact check with each selector, no Pact CLI equivalent, and the REST route', () => {
    const surfaces = pactCommandSurfaces(checkCommandAction({ selectors: ['main', 'deployed:production'], tenant: 'acme' }));
    const text = Object.fromEntries(surfaces.map((surface) => [surface.id, surface.text ?? surface.unavailable ?? '']));
    expect(text.apiome).toContain('apiome pact check pacts/');
    expect(text.apiome).toContain('--against main');
    expect(text.apiome).toContain('--against deployed:production');
    expect(text['pact-cli']).toMatch(/no|not/i);
    expect(text.rest).toContain('POST /v1/tenants/acme/pact-broker/pacts/check');
  });

  it('falls back to main when nothing is chosen', () => {
    expect(checkCommandAction({ selectors: [], tenant: '' }).options?.[0].value).toEqual(['main']);
  });
});
