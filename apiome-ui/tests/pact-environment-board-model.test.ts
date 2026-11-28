/**
 * The what-is-where board, the history and the endings — PFX-8.13 (#7310), the pure parts.
 *
 * * `lib/pact-environment-board.ts`: the history query check, the dot and its words, the line under
 *   a version, the "can go" label, the facts strip, the simulator link, who is deployed where, and
 *   the timeline's title, detail and badge;
 * * `lib/pact-environment-endings.ts`: the body checks (unknown fields refused by name), which
 *   deployment an undeployment ends (`pact-broker`'s rule) and the commands;
 * * the two proxy handlers against a fake REST: the calls they make, a refusal kept, nothing ended
 *   on a guess.
 */

import fixture from './fixtures/pact-environments.json';
import {
  boardFacts,
  deployedIn,
  dotTone,
  eventBadge,
  eventDetail,
  eventTitle,
  nextLabel,
  pickEventsQuery,
  simulatorEnvironment,
  versionNote,
  type Board,
  type HistoryEvent,
} from '../lib/pact-environment-board';
import {
  checkSupportEndedBody,
  checkUndeploymentBody,
  parseCurrentlyDeployed,
  parseCurrentlySupported,
  supportEndedCommandAction,
  undeploymentCommandAction,
  undeploymentTargets,
} from '../lib/pact-environment-endings';
import { recordSupportEnded, recordUndeployment } from '../lib/pact-environment-writes-proxy';
import { pactCommandSurfaces } from '../lib/pact-commands';
import type { RestCall } from '../lib/pact-provider-contract-proxy';

const BOARD = fixture.board as unknown as Board;
const EVENTS = fixture.events.events as unknown as HistoryEvent[];
const YES = { checked: true as const, deployable: true, reason: 'ok', counts: {} };

describe('the history query', () => {
  it('forwards the filters with a fixed page size', () => {
    const picked = pickEventsQuery(new URLSearchParams('environment=production&cursor=abc'));
    expect(picked).toEqual({ ok: true, query: expect.any(URLSearchParams) });
    expect(picked.ok && picked.query.toString()).toBe('environment=production&cursor=abc&limit=25');
  });

  it.each([
    ['limit=5', 'Unsupported parameter limit'],
    ['environment=a&environment=b', 'more than once'],
    ['pacticipant=%20', 'is empty'],
    [`cursor=${'x'.repeat(201)}`, 'longer than 200'],
  ])('refuses %s', (query, error) => {
    const picked = pickEventsQuery(new URLSearchParams(query));
    expect(picked.ok).toBe(false);
    expect(!picked.ok && picked.error).toContain(error);
  });
});

describe('drawing the board', () => {
  it('gives each verdict its dot', () => {
    expect(dotTone(YES)).toBe('ok');
    expect(dotTone({ ...YES, deployable: false })).toBe('danger');
    expect(dotTone({ ...YES, deployable: null })).toBe('warn');
    expect(dotTone({ checked: false, notChecked: 'budget' })).toBe('neutral');
  });

  it('writes the instances and what is wrong under a version', () => {
    const version = { version: '1', deployedAt: null, applicationInstances: ['eu-west', null], verdict: YES };
    expect(versionNote(version)).toBe('eu-west');
    expect(versionNote({ ...version, verdict: { ...YES, deployable: false, counts: { failed: 1 } } })).toBe('eu-west · 1 failing pact');
    expect(versionNote({ ...version, applicationInstances: [null], verdict: { ...YES, deployable: false, counts: { failed: 3 } } })).toBe(
      '3 failing pacts',
    );
    expect(versionNote({ ...version, applicationInstances: [null], verdict: { ...YES, deployable: null } })).toBe('unverified');
    expect(versionNote({ ...version, applicationInstances: [null], verdict: { checked: false, notChecked: 'x' } })).toBe('not checked');
  });

  it('says whether the next version can go', () => {
    expect(nextLabel({ version: '2', from: 'staging', verdict: YES })).toEqual({ text: '2 can go', tone: 'ok', canGo: true });
    expect(nextLabel({ version: '2', from: 'staging', verdict: { ...YES, deployable: false } }).text).toBe('2 blocked');
    expect(nextLabel({ version: '2', from: 'staging', verdict: { ...YES, deployable: null } }).canGo).toBe(false);
    expect(nextLabel({ version: '2', from: 'staging', verdict: { checked: false, notChecked: 'x' } }).text).toBe('2 not checked');
  });

  it('counts the facts strip and finds the simulator and what runs where', () => {
    expect(boardFacts(BOARD)).toEqual({ environments: 3, services: 5, running: 6, blocked: 1 });
    expect(simulatorEnvironment(BOARD)).toBe('production');
    expect(simulatorEnvironment({ ...BOARD, environments: BOARD.environments.filter((e) => !e.production) })).toBe('staging');
    expect(simulatorEnvironment({ ...BOARD, environments: [] })).toBeNull();
    const production = BOARD.environments[2].uuid;
    expect(deployedIn(BOARD, production).map((entry) => entry.pacticipant.slug)).toEqual(['billing-service', 'ledger-api', 'reporting-job']);
    expect(deployedIn(BOARD, production)[2].versions).toEqual([
      { version: '1.4.2', instance: 'eu-west' },
      { version: '1.4.2', instance: 'us-east' },
    ]);
    expect(deployedIn(BOARD, 'nowhere')).toEqual([]);
  });
});

describe('drawing the history', () => {
  it('titles, details and badges each kind of event', () => {
    expect(eventTitle(EVENTS[0])).toBe('Billing Service 2.4.0 deployed to Staging');
    expect(eventDetail(EVENTS[0])).toBe('Replaced 2.3.1');
    expect(eventBadge(EVENTS[0])).toEqual({ label: 'Not verified at the time', variant: 'warn' });
    expect(eventBadge(EVENTS[1])).toEqual({ label: 'Verified at the time', variant: 'ok' });
    expect(eventTitle(EVENTS[2])).toBe('Mobile App 5.1.0 — support ended in Production');
    expect(eventDetail(EVENTS[2])).toContain('no longer hold');
    expect(eventBadge(EVENTS[2])).toBeNull();
    expect(eventTitle(EVENTS[3])).toBe('Reporting Job 1.4.1 undeployed from Production');
    expect(eventDetail(EVENTS[3])).toBe('instance ap-south · No longer running there');
    expect(eventTitle(EVENTS[4])).toBe('Mobile App 5.2.0 released to Production');
    expect(eventBadge({ ...EVENTS[4], verdict: 'unknown' })?.label).toBe('Not verified at the time');
    expect(eventBadge({ ...EVENTS[4], verdict: null })).toBeNull();
  });
});

describe('the ending bodies', () => {
  it('accepts an undeployment with or without an instance, and refuses anything else by name', () => {
    expect(checkUndeploymentBody({ pacticipant: 'billing-service' })).toEqual({ ok: true, body: { pacticipant: 'billing-service' } });
    expect(checkUndeploymentBody({ pacticipant: 'b', applicationInstance: 'eu' }).ok).toBe(true);
    expect(checkUndeploymentBody({ pacticipant: 'b', version: '1' })).toEqual({
      ok: false,
      error: 'Not an undeployment field: version. Send only pacticipant, applicationInstance.',
    });
    expect(checkUndeploymentBody({ pacticipant: ' ' })).toEqual({ ok: false, error: 'pacticipant must be non-empty text.' });
    expect(checkUndeploymentBody({ pacticipant: 'b', applicationInstance: '' }).ok).toBe(false);
    expect(checkUndeploymentBody([])).toEqual({ ok: false, error: 'Send a JSON object.' });
  });

  it('needs the service and the version to end support', () => {
    expect(checkSupportEndedBody({ pacticipant: 'm', version: '1' }).ok).toBe(true);
    expect(checkSupportEndedBody({ pacticipant: 'm' })).toEqual({ ok: false, error: 'version must be non-empty text.' });
    expect(checkSupportEndedBody({ pacticipant: 'm', version: '1', environment: 'p' }).ok).toBe(false);
  });
});

describe("which deployment an undeployment ends (pact-broker's rule)", () => {
  const entries = [
    { uuid: 'd1', applicationInstance: null, version: '1' },
    { uuid: 'd2', applicationInstance: 'eu', version: '2' },
  ];
  const context = { pacticipant: 'Billing', environment: 'production' };

  it('ends the named instance, or the unnamed one', () => {
    expect(undeploymentTargets(entries, { ...context, applicationInstance: 'eu' })).toEqual({ ok: true, targets: [entries[1]] });
    expect(undeploymentTargets(entries, { ...context, applicationInstance: null })).toEqual({ ok: true, targets: [entries[0]] });
  });

  it('says what is deployed instead of guessing', () => {
    expect(undeploymentTargets([], { ...context, applicationInstance: null })).toEqual({
      ok: false,
      error: 'Billing is not currently deployed to production environment. Cannot record undeployment.',
    });
    const named = undeploymentTargets([entries[1], { uuid: 'd3', applicationInstance: 'au', version: '2' }], {
      ...context,
      applicationInstance: null,
    });
    expect(!named.ok && named.error).toBe('Please specify one of the following application instances to record the undeployment from: au, eu');
    const missing = undeploymentTargets([entries[0]], { ...context, applicationInstance: 'us' });
    expect(!missing.ok && missing.error).toContain("application instance 'us'");
    expect(!missing.ok && missing.error).toContain('the unnamed instance');
  });

  it('reads REST’s lists', () => {
    expect(
      parseCurrentlyDeployed({
        _embedded: {
          deployedVersions: [
            { uuid: 'd1', applicationInstance: null, _embedded: { version: { number: '1' } } },
            { applicationInstance: 'eu' },
          ],
        },
      }),
    ).toEqual([{ uuid: 'd1', applicationInstance: null, version: '1' }]);
    expect(parseCurrentlyDeployed(null)).toEqual([]);
    expect(parseCurrentlySupported({ _embedded: { releasedVersions: [{ uuid: 'r1' }, {}] } })).toEqual(['r1']);
  });
});

describe('the same, from anywhere', () => {
  it('writes record-undeployment and record-support-ended with their PATCHes', () => {
    const undeploy = pactCommandSurfaces(
      undeploymentCommandAction({ pacticipant: 'billing-service', environment: 'production', applicationInstance: 'eu-west' }, 'acme'),
    );
    const text = JSON.stringify(undeploy);
    expect(text).toContain('apiome pact record-undeployment');
    expect(text).toContain('--application-instance eu-west');
    expect(text).toContain('PATCH');
    expect(text).toContain('/v1/tenants/acme/pact-broker/deployed-versions/{deployment}');
    const unnamed = JSON.stringify(
      pactCommandSurfaces(undeploymentCommandAction({ pacticipant: 'b', environment: 'production', applicationInstance: '' })),
    );
    expect(unnamed).not.toContain('--application-instance');
    const ended = JSON.stringify(
      pactCommandSurfaces(supportEndedCommandAction({ pacticipant: 'mobile-app', version: '1.8.7', environment: 'production' })),
    );
    expect(ended).toContain('apiome pact record-support-ended');
    expect(ended).toContain('--version 1.8.7');
    expect(ended).toContain('currentlySupported');
  });
});

/** A fake REST: answers by `METHOD path` prefix and records the calls. */
function fakeRest(answers: Record<string, { status: number; body: unknown } | null>) {
  const calls: Array<{ method: string; path: string; body?: unknown }> = [];
  const call: RestCall = async (method, path, body) => {
    calls.push({ method, path, body });
    const key = Object.keys(answers)
      .sort((a, b) => b.length - a.length)
      .find((candidate) => `${method} ${path}`.startsWith(candidate));
    return key ? answers[key] : { status: 404, body: { detail: 'not found' } };
  };
  return { call, calls };
}

const ENVIRONMENTS = {
  status: 200,
  body: { _embedded: { environments: [{ uuid: 'env-1', name: 'production', displayName: 'Production', production: true }] } },
};

describe('the proxies', () => {
  it('ends the deployment pact-broker would end', async () => {
    const { call, calls } = fakeRest({
      'GET pact-broker/environments?name=production': ENVIRONMENTS,
      'GET pact-broker/environments/env-1/deployed-versions/currently-deployed?pacticipant=billing-service': {
        status: 200,
        body: {
          _embedded: {
            deployedVersions: [
              { uuid: 'd1', applicationInstance: null, _embedded: { version: { number: '2.3.1' } } },
              { uuid: 'd2', applicationInstance: 'eu', _embedded: { version: { number: '2.4.0' } } },
            ],
          },
        },
      },
      'PATCH pact-broker/deployed-versions/d2': { status: 200, body: { uuid: 'd2' } },
    });
    const answer = await recordUndeployment(call, 'production', { pacticipant: 'billing-service', applicationInstance: 'eu' });
    expect(answer).toEqual({ status: 200, body: { undeployed: [{ uuid: 'd2', applicationInstance: 'eu', version: '2.4.0' }] } });
    expect(calls[2]).toEqual({ method: 'PATCH', path: 'pact-broker/deployed-versions/d2', body: { currentlyDeployed: false } });
  });

  it('ends nothing when nothing matches, and keeps REST’s refusal', async () => {
    const empty = fakeRest({
      'GET pact-broker/environments?name=production': ENVIRONMENTS,
      'GET pact-broker/environments/env-1/deployed-versions': { status: 200, body: { _embedded: { deployedVersions: [] } } },
    });
    const none = await recordUndeployment(empty.call, 'production', { pacticipant: 'billing-service' });
    expect(none.status).toBe(404);
    expect(none.body.error).toContain('is not currently deployed to production');
    expect(empty.calls.map((c) => c.method)).toEqual(['GET', 'GET']);

    const refused = fakeRest({
      'GET pact-broker/environments?name=production': ENVIRONMENTS,
      'GET pact-broker/environments/env-1/deployed-versions': {
        status: 200,
        body: { _embedded: { deployedVersions: [{ uuid: 'd1', applicationInstance: null }] } },
      },
      'PATCH pact-broker/deployed-versions/d1': { status: 403, body: { detail: 'Permission denied: pacts:edit' } },
    });
    const denied = await recordUndeployment(refused.call, 'production', { pacticipant: 'billing-service' });
    expect(denied.status).toBe(403);
  });

  it('ends support for the release that is supported, or says it is not released', async () => {
    const { call, calls } = fakeRest({
      'GET pact-broker/environments?name=production': ENVIRONMENTS,
      'GET pact-broker/environments/env-1/released-versions/currently-supported?pacticipant=mobile-app&version=5.1.0': {
        status: 200,
        body: { _embedded: { releasedVersions: [{ uuid: 'r1' }] } },
      },
      'PATCH pact-broker/released-versions/r1': { status: 200, body: { uuid: 'r1' } },
    });
    expect(await recordSupportEnded(call, 'production', { pacticipant: 'mobile-app', version: '5.1.0' })).toEqual({
      status: 200,
      body: { ended: 1 },
    });
    expect(calls[2].body).toEqual({ currentlySupported: false });

    const none = fakeRest({
      'GET pact-broker/environments?name=production': ENVIRONMENTS,
      'GET pact-broker/environments/env-1/released-versions': { status: 200, body: { _embedded: { releasedVersions: [] } } },
    });
    const answer = await recordSupportEnded(none.call, 'production', { pacticipant: 'mobile-app', version: '9' });
    expect(answer.status).toBe(404);
    expect(answer.body.error).toBe('mobile-app version 9 is not currently released in production environment. Cannot record support ended.');
  });

  it('answers 503 when REST cannot be reached and 404 for an unknown environment', async () => {
    const down = fakeRest({ 'GET pact-broker/environments': null });
    expect((await recordSupportEnded(down.call, 'production', { pacticipant: 'm', version: '1' })).status).toBe(503);
    const unknown = fakeRest({ 'GET pact-broker/environments': { status: 200, body: { _embedded: { environments: [] } } } });
    expect((await recordUndeployment(unknown.call, 'moon', { pacticipant: 'm' })).status).toBe(404);
  });
});
