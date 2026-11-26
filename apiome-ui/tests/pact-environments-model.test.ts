/**
 * @jest-environment node
 */
/**
 * Environments and deployments dashboard — PFX-5.7 (#6951): the model and the proxies.
 *
 * * **Routes and paths**: the page routes, the REST paths, environment names and route segments.
 * * **Queries**: the simulator takes `pacticipant`, `version` and `applicationInstance` only; the
 *   history `pacticipant` and a numeric `cursor`; anything else refused with a sentence naming it.
 * * **Form**: read from and written to the address; what a person can fix is caught first.
 * * **Drawing**: the grid of pacticipants × environments, the history filter's choices, effects,
 *   verdict words, placements, the summary line, the replacement sentence and the CLI commands.
 * * **Proxies**: forward as the signed-in user in the session tenant; refuse bad input without
 *   calling REST; keep REST's refusal and the session's own.
 */

import { jest } from '@jest/globals';
import { NextRequest, NextResponse } from 'next/server';

let tenant: { user: { user_id: string }; slug: string } | { error: NextResponse } = {
  user: { user_id: 'u-1' },
  slug: 'acme',
};
const forwarded: Array<{ url: string; method: string }> = [];
let restAnswer: { status: number; body: unknown } = { status: 200, body: { ok: true } };

jest.mock('@lib/connectors-proxy', () => ({
  resolveConnectorTenant: async () => tenant,
  tenantUrl: (slug: string, path: string) => `http://rest/v1/tenants/${slug}/${path}`,
  forwardConnectorRequest: async (url: string, init: { method: string }) => {
    forwarded.push({ url, method: init.method });
    return restAnswer.status < 400
      ? NextResponse.json(restAnswer.body)
      : NextResponse.json({ success: false, error: 'Unknown environment production' }, { status: restAnswer.status });
  },
}));

jest.mock('@lib/rest-auth', () => ({
  createRestAuthHeaders: () => ({ Authorization: 'Bearer session' }),
  REST_API_BASE_URL: 'http://rest/v1',
}));

import {
  ENVIRONMENTS_ROUTE,
  buildGrid,
  effectLabel,
  environmentFromSegment,
  environmentPacticipants,
  environmentRoute,
  historyProxyPath,
  historyQueryProblem,
  isEnvironmentName,
  pickSimulationQuery,
  placementLabel,
  replacementSentence,
  simulateProxyPath,
  simulationCommands,
  simulationFormFrom,
  simulationFormProblem,
  simulationParams,
  simulatorRoute,
  summaryLine,
  verdictWord,
  type Simulation,
  type Topology,
} from '../lib/pact-environments';
import { GET as topologyGet } from '../src/app/api/pact/environment-topology/route';
import { GET as historyGet } from '../src/app/api/pact/environments/[environment]/deployments/route';
import { GET as simulateGet } from '../src/app/api/pact/environments/[environment]/simulate/route';
import fixture from './fixtures/pact-environments.json';

const TOPOLOGY = fixture.topology as unknown as Topology;
const SIMULATION = fixture.simulation as unknown as Simulation;

describe('routes and REST paths', () => {
  it('builds the page routes and REST paths, encoding the name', () => {
    expect(ENVIRONMENTS_ROUTE).toBe('/ade/dashboard/pacts/environments');
    expect(environmentRoute('production')).toBe('/ade/dashboard/pacts/environments/production');
    expect(environmentRoute('eu#1')).toBe('/ade/dashboard/pacts/environments/eu%231');
    expect(simulatorRoute('production')).toBe('/ade/dashboard/pacts/environments/production/simulate');
    expect(simulatorRoute('production', new URLSearchParams({ pacticipant: 'ledger-api', version: 'p-2' }))).toBe(
      '/ade/dashboard/pacts/environments/production/simulate?pacticipant=ledger-api&version=p-2',
    );
    expect(historyProxyPath('prod/eu')).toBe('pact-environments/prod%2Feu/deployments');
    expect(simulateProxyPath('production')).toBe('pact-environments/production/simulate');
  });

  it('accepts the names V435 allows and nothing else', () => {
    expect(isEnvironmentName('production')).toBe(true);
    expect(isEnvironmentName('eu-west.1')).toBe(true);
    expect(isEnvironmentName('')).toBe(false);
    expect(isEnvironmentName('two words')).toBe(false);
    expect(isEnvironmentName('tab\there')).toBe(false);
    expect(isEnvironmentName('x'.repeat(256))).toBe(false);
  });

  it('reads a route segment, encoded or not', () => {
    expect(environmentFromSegment('eu%231')).toBe('eu#1');
    expect(environmentFromSegment('production')).toBe('production');
    expect(environmentFromSegment('100%')).toBe('100%');
  });
});

describe('queries', () => {
  const picked = (query: string) => pickSimulationQuery(new URLSearchParams(query));

  it('keeps a whole simulator question', () => {
    const answer = picked('pacticipant=ledger-api&version=p-2&applicationInstance=eu-west');
    expect(answer.ok && answer.query.toString()).toBe('pacticipant=ledger-api&version=p-2&applicationInstance=eu-west');
  });

  it.each([
    ['version=1', 'The pacticipant parameter is missing.'],
    ['pacticipant=a', 'The version parameter is missing.'],
    ['pacticipant=a&version=1&ignore=b', 'Unsupported parameter ignore'],
    ['pacticipant=a&pacticipant=b&version=1', 'given more than once'],
    ['pacticipant=&version=1', 'The pacticipant parameter is empty.'],
    [`pacticipant=${'a'.repeat(256)}&version=1`, 'longer than 255'],
  ])('refuses %s', (query, message) => {
    const answer = picked(query);
    expect(answer.ok).toBe(false);
    expect(!answer.ok && answer.error).toContain(message);
  });

  it('accepts only a numeric history cursor', () => {
    expect(historyQueryProblem(new URLSearchParams('cursor=17'))).toBeNull();
    expect(historyQueryProblem(new URLSearchParams())).toBeNull();
    expect(historyQueryProblem(new URLSearchParams('cursor=abc'))).toBe('The cursor is not valid.');
    expect(historyQueryProblem(new URLSearchParams(`cursor=${'1'.repeat(20)}`))).toBe('The cursor is not valid.');
  });
});

describe('the simulator form', () => {
  it('reads the address and writes it back, leaving blanks out', () => {
    const form = simulationFormFrom(new URLSearchParams('pacticipant=ledger-api&version=p-2'));
    expect(form).toEqual({ pacticipant: 'ledger-api', version: 'p-2', applicationInstance: '' });
    expect(simulationParams({ ...form, pacticipant: '  ledger-api ' }).toString()).toBe('pacticipant=ledger-api&version=p-2');
    expect(simulationParams({ ...form, applicationInstance: 'eu-west' }).get('applicationInstance')).toBe('eu-west');
  });

  it('says what is missing or malformed before asking', () => {
    const form = { pacticipant: 'ledger-api', version: 'p-2', applicationInstance: '' };
    expect(simulationFormProblem(form)).toBeNull();
    expect(simulationFormProblem({ ...form, pacticipant: ' ' })).toBe('Name the pacticipant to deploy.');
    expect(simulationFormProblem({ ...form, version: '' })).toBe('Name the version to deploy.');
    expect(simulationFormProblem({ ...form, applicationInstance: ' eu' })).toContain('cannot start or end with a space');
  });
});

describe('drawing', () => {
  it('lays out every pacticipant in any environment, by name, one cell per environment', () => {
    const grid = buildGrid(TOPOLOGY);
    expect(grid.map((row) => row.pacticipant.name)).toEqual(['Billing Service', 'Ledger API', 'Mobile App', 'Reporting Job']);
    const [billing, , mobile, reporting] = grid;
    expect(billing.cells.map((cell) => cell.deployed.map((d) => d.version))).toEqual([['2.3.1'], ['2.4.0'], []]);
    expect(mobile.cells[0].released.map((r) => r.version)).toEqual(['5.2.0']);
    expect(reporting.cells[0].deployed.map((d) => d.applicationInstance)).toEqual(['eu-west', 'us-east']);
    expect(buildGrid({ environments: [], truncated: false })).toEqual([]);
  });

  it('offers each pacticipant of an environment once in the history filter', () => {
    expect(environmentPacticipants(TOPOLOGY.environments[0]).map((p) => p.slug)).toEqual([
      'billing-service',
      'ledger-api',
      'mobile-app',
      'reporting-job',
    ]);
  });

  it('names effects, verdicts and placements', () => {
    expect(effectLabel('breaks')).toEqual({ label: 'Breaks', variant: 'danger' });
    expect(effectLabel('clears')).toEqual({ label: 'Clears', variant: 'ok' });
    expect(effectLabel('unchanged')).toEqual({ label: 'No change', variant: 'neutral' });
    expect(effectLabel('mystery')).toEqual({ label: 'mystery', variant: 'neutral' });
    expect(verdictWord(true).label).toBe('Deployable');
    expect(verdictWord(false).label).toBe('Not deployable');
    expect(verdictWord(null).label).toBe('Not known yet');
    const [pending, , running] = SIMULATION.impacts;
    expect(placementLabel(pending, 'production')).toBe('In staging');
    expect(placementLabel(running, 'production')).toBe('Running in production');
    expect(placementLabel({ ...pending, environments: [] }, 'production')).toBe('Elsewhere');
  });

  it('summarises the effects, what needs attention first', () => {
    expect(summaryLine(SIMULATION.summary)).toBe('1 clears · 2 no change');
    expect(summaryLine({ breaks: 1, fixes: 2 })).toBe('1 breaks · 2 fixes');
    expect(summaryLine({})).toBe('Nothing checked');
  });

  it('says what the deployment would replace', () => {
    expect(replacementSentence(SIMULATION)).toBe(
      'Would replace Ledger API 3f2a9c1b7e6d4a5b8c9d0e1f2a3b4c5d6e7f8a9b in production (the unnamed instance).',
    );
    expect(replacementSentence({ ...SIMULATION, alreadyDeployed: true })).toContain('is already deployed to production');
    expect(replacementSentence({ ...SIMULATION, replaces: null, applicationInstance: 'eu-west' })).toBe(
      'Ledger API has nothing deployed to production (instance eu-west) yet; this would be its first deployment there.',
    );
  });

  it('gives the pipeline commands, shell-quoted, with the instance when there is one', () => {
    const commands = simulationCommands({ ...SIMULATION, applicationInstance: 'eu west' });
    expect(commands).toContain('apiome pact can-i-deploy \\\n  --pacticipant ledger-api');
    expect(commands).toContain('  --to-environment production');
    expect(commands).toContain('&& apiome pact record-deployment');
    expect(commands).toContain("  --application-instance 'eu west'");
    expect(simulationCommands(SIMULATION)).not.toContain('--application-instance');
  });
});

describe('the /api/pact proxies', () => {
  const ctx = (environment: string) => ({ params: Promise.resolve({ environment }) }) as never;
  const req = (path: string) => new NextRequest(`http://ui${path}`);
  const rest = 'http://rest/v1/tenants/acme';

  beforeEach(() => {
    tenant = { user: { user_id: 'u-1' }, slug: 'acme' };
    forwarded.length = 0;
    restAnswer = { status: 200, body: { ok: true } };
  });

  it('forwards the topology, the history and the simulator to their REST routes', async () => {
    await topologyGet(req('/api/pact/environment-topology'));
    await historyGet(req('/api/pact/environments/production/deployments?pacticipant=ledger-api&cursor=17'), ctx('production'));
    await simulateGet(
      req('/api/pact/environments/production/simulate?pacticipant=ledger-api&version=p-2&applicationInstance=eu-west'),
      ctx('production'),
    );
    await historyGet(req('/api/pact/environments/eu%231/deployments'), ctx('eu%231'));
    expect(forwarded).toEqual([
      { method: 'GET', url: `${rest}/pact-environments` },
      { method: 'GET', url: `${rest}/pact-environments/production/deployments?limit=25&pacticipant=ledger-api&cursor=17` },
      {
        method: 'GET',
        url: `${rest}/pact-environments/production/simulate?pacticipant=ledger-api&version=p-2&applicationInstance=eu-west`,
      },
      { method: 'GET', url: `${rest}/pact-environments/eu%231/deployments?limit=25` },
    ]);
  });

  it('refuses bad input without calling REST', async () => {
    const answers = [
      await topologyGet(req('/api/pact/environment-topology?x=1')),
      await historyGet(req('/api/pact/environments/two%20words/deployments'), ctx('two%20words')),
      await historyGet(req('/api/pact/environments/production/deployments?label=x'), ctx('production')),
      await historyGet(req('/api/pact/environments/production/deployments?cursor=abc'), ctx('production')),
      await historyGet(req('/api/pact/environments/production/deployments?pacticipant='), ctx('production')),
      await simulateGet(req('/api/pact/environments/two%20words/simulate?pacticipant=a&version=1'), ctx('two%20words')),
      await simulateGet(req('/api/pact/environments/production/simulate?pacticipant=a'), ctx('production')),
      await simulateGet(req('/api/pact/environments/production/simulate?pacticipant=a&version=1&to=x'), ctx('production')),
    ];
    expect(answers.map((answer) => answer.status)).toEqual([400, 404, 400, 400, 400, 404, 400, 400]);
    expect(((await answers[0].json()) as { error: string }).error).toContain('Unsupported parameter x');
    expect(((await answers[6].json()) as { error: string }).error).toBe('The version parameter is missing.');
    expect(forwarded).toHaveLength(0);
  });

  it('keeps REST’s refusal and the session’s own', async () => {
    restAnswer = { status: 404, body: {} };
    const refused = await simulateGet(
      req('/api/pact/environments/production/simulate?pacticipant=a&version=1'),
      ctx('production'),
    );
    expect(refused.status).toBe(404);
    tenant = { error: NextResponse.json({ success: false, error: 'Unauthorized' }, { status: 401 }) };
    expect((await topologyGet(req('/api/pact/environment-topology'))).status).toBe(401);
    expect(forwarded).toHaveLength(1);
  });
});
