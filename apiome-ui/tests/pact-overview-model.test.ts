/**
 * @jest-environment node
 */
/**
 * The shared model of the **Contracts** landing and tab row — PFX-8.1 (#7298).
 *
 * * the tab row: shipped destinations only, one per id;
 * * the landing's address: defaults left out; anything unusable falls back **and is reported**;
 * * the proxy's query checks (unknown, repeated, empty, out-of-range refused, naming them) and the
 *   REST path in a fixed order; the proxy forwards a checked read and refuses bad input without
 *   calling REST;
 * * the wording: verdicts, initials, pair lists;
 * * the status strip's statuses, the first-run checklist, the network view;
 * * every `apiome pact` command "Start something" shows is a registered CLI verb.
 */

import { jest } from '@jest/globals';
import { readFileSync } from 'fs';
import { join } from 'path';
import { NextRequest, NextResponse } from 'next/server';

const forwarded: string[] = [];

jest.mock('@lib/connectors-proxy', () => ({
  resolveConnectorTenant: async () => ({ user: { user_id: 'u-1' }, slug: 'acme' }),
  tenantUrl: (slug: string, path: string) => `http://rest/v1/tenants/${slug}/${path}`,
  forwardConnectorRequest: async (url: string) => {
    forwarded.push(url);
    return NextResponse.json({ ok: true });
  },
}));

jest.mock('@lib/rest-auth', () => ({
  createRestAuthHeaders: () => ({ Authorization: 'Bearer session' }),
  REST_API_BASE_URL: 'http://rest/v1',
}));

import { GET as integrationsGet } from '../src/app/api/pact/integrations/route';
import {
  CONTRACTS_ROUTE,
  CONTRACTS_TABS,
  INTEGRATIONS_PAGE_SIZE,
  MAX_PAGE,
  WAYS_IN,
  firstRunSteps,
  initials,
  integrationsNetwork,
  integrationsProxyPath,
  integrationsQuery,
  integrationsQueryProblem,
  overviewRoute,
  overviewStatuses,
  pairList,
  readOverviewQuery,
  verdictText,
  type PactIntegrationsPage,
} from '../lib/pact-overview';
import fixture from './fixtures/pact-overview.json';

const page = fixture.page as unknown as PactIntegrationsPage;

describe('the tab row', () => {
  it('lists the shipped Contracts pages, Overview first, each id once', () => {
    expect(CONTRACTS_TABS.map((tab) => tab.label)).toEqual([
      'Overview',
      'Pacticipants',
      'Matrix',
      'Can I deploy',
      'Verification',
      'Environments',
      'Webhooks',
      'Health',
      'Settings',
    ]);
    expect(new Set(CONTRACTS_TABS.map((tab) => tab.id)).size).toBe(CONTRACTS_TABS.length);
    expect(CONTRACTS_TABS[0].href).toBe(CONTRACTS_ROUTE);
    for (const tab of CONTRACTS_TABS) expect(tab.href.startsWith(CONTRACTS_ROUTE)).toBe(true);
  });

  it('only links to routes that have a page', () => {
    const app = join(__dirname, '..', 'src', 'app');
    for (const tab of CONTRACTS_TABS) {
      expect(() => readFileSync(join(app, tab.href, 'page.tsx'))).not.toThrow();
    }
  });
});

describe("the landing's address", () => {
  it('reads defaults from an empty address', () => {
    expect(readOverviewQuery({})).toEqual({ q: '', filter: 'all', page: 1, view: 'table', problems: [] });
  });

  it('reads a search, a chip, a page and the network view', () => {
    expect(readOverviewQuery({ q: ' billing ', filter: 'failing', page: '2', view: 'network' })).toEqual({
      q: 'billing',
      filter: 'failing',
      page: 2,
      view: 'network',
      problems: [],
    });
  });

  it.each([
    [{ filter: 'red' }, 'There is no filter called “red”'],
    [{ page: '0' }, 'Page “0” does not exist'],
    [{ page: 'two' }, 'Page “two” does not exist'],
    [{ page: String(MAX_PAGE + 1) }, 'does not exist'],
    [{ view: 'cards' }, 'There is no “cards” view'],
    [{ q: 'x'.repeat(101) }, 'shortened'],
    [{ filter: ['stale', 'failing'] }, 'given more than once'],
  ])('reports what it cannot use (%j) instead of dropping it', (query, problem) => {
    const read = readOverviewQuery(query);
    expect(read.problems).toHaveLength(1);
    expect(read.problems[0]).toContain(problem);
  });

  it('writes a state back without its defaults', () => {
    expect(overviewRoute()).toBe(CONTRACTS_ROUTE);
    expect(overviewRoute({ q: '', filter: 'all', page: 1, view: 'table' })).toBe(CONTRACTS_ROUTE);
    expect(overviewRoute({ q: 'pay', filter: 'stale', page: 3, view: 'network' })).toBe(
      `${CONTRACTS_ROUTE}?q=pay&filter=stale&page=3&view=network`,
    );
  });

  it("turns a page into the proxy's limit and offset", () => {
    expect(integrationsQuery({ q: '', filter: 'all', page: 1 })).toBe(`limit=${INTEGRATIONS_PAGE_SIZE}`);
    expect(integrationsQuery({ q: 'pay', filter: 'mine', page: 3 })).toBe(
      `q=pay&filter=mine&limit=${INTEGRATIONS_PAGE_SIZE}&offset=${2 * INTEGRATIONS_PAGE_SIZE}`,
    );
  });
});

describe('the proxy', () => {
  const req = (url: string) => new NextRequest(new URL(url, 'http://ui'));

  beforeEach(() => {
    forwarded.length = 0;
  });

  it.each([
    ['cursor=2', 'Unsupported parameter cursor'],
    ['filter=red', 'filter parameter must be one of'],
    ['filter=stale&filter=failing', 'given more than once'],
    ['q=', 'q parameter is empty'],
    [`q=${'x'.repeat(101)}`, 'longer than 100'],
    ['limit=0', 'limit parameter'],
    ['limit=101', 'limit parameter'],
    ['limit=1.5', 'limit parameter'],
    ['offset=-1', 'offset parameter'],
    ['offset=1001', 'offset parameter'],
  ])('refuses %s naming the problem', (query, problem) => {
    expect(integrationsQueryProblem(new URLSearchParams(query))).toContain(problem);
  });

  it('accepts every documented parameter', () => {
    expect(integrationsQueryProblem(new URLSearchParams('q=pay&filter=mine&limit=25&offset=1000'))).toBeNull();
  });

  it('builds the REST path in a fixed order', () => {
    expect(integrationsProxyPath(new URLSearchParams('offset=25&filter=stale&q=pay&limit=25'))).toBe(
      'pact-integrations?q=pay&filter=stale&limit=25&offset=25',
    );
    expect(integrationsProxyPath(new URLSearchParams())).toBe('pact-integrations');
  });

  it('forwards a checked read as the signed-in user', async () => {
    await integrationsGet(req('/api/pact/integrations?filter=failing&limit=25'));
    await integrationsGet(req('/api/pact/integrations'));
    expect(forwarded).toEqual([
      'http://rest/v1/tenants/acme/pact-integrations?filter=failing&limit=25',
      'http://rest/v1/tenants/acme/pact-integrations',
    ]);
  });

  it('refuses bad input with a 400 without calling REST', async () => {
    const answer = await integrationsGet(req('/api/pact/integrations?filter=red'));
    expect(answer.status).toBe(400);
    expect(((await answer.json()) as { error: string }).error).toContain('filter parameter');
    expect(forwarded).toEqual([]);
  });
});

describe('wording', () => {
  it('reads every verdict, and an unknown one as not verified yet', () => {
    expect(verdictText('failing')).toEqual({ label: 'Failing', status: 'failed' });
    expect(verdictText('no-provider-contract').label).toBe('No provider contract');
    expect(verdictText('verified').status).toBe('passed');
    expect(verdictText('something-new').label).toBe('Not verified yet');
  });

  it('takes two initials, or one for a one-word name', () => {
    expect(initials('Orders UI')).toBe('OU');
    expect(initials('billing-service')).toBe('BS');
    expect(initials('Checkout')).toBe('C');
    expect(initials('  ')).toBe('?');
  });

  it('names pairs as a sentence, with how many more there are', () => {
    const refs = page.attention.failing;
    expect(pairList(refs, 1)).toBe('Orders UI → Billing Service');
    expect(pairList([...refs, ...page.attention.stale], 2)).toBe(
      'Orders UI → Billing Service and Mobile App → Payments API',
    );
    expect(pairList(refs, 4)).toBe('Orders UI → Billing Service and 3 more');
  });
});

describe('the status strip', () => {
  it('says failing, stale, provider-less and pending, in that order', () => {
    const statuses = overviewStatuses(page);
    expect(statuses.map((status) => [status.id, status.tone, status.label])).toEqual([
      ['failing', 'danger', '1 failing'],
      ['stale', 'warn', '1 stale'],
      ['no-provider-contract', 'warn', '1 without a provider contract'],
      ['pending', 'accent', '1 pending'],
    ]);
    expect(statuses[0].title).toBe('Orders UI → Billing Service failed its newest verification.');
    expect(statuses[0].action?.href).toBe(`${CONTRACTS_ROUTE}?filter=failing`);
    expect(statuses[2].title).toContain('Checkout → Payments API has a pact');
  });

  it('is empty when nothing needs attention', () => {
    const calm = { ...page, counts: { ...page.counts, failing: 0, stale: 0, no_provider_contract: 0, pending: 0 } };
    expect(overviewStatuses(calm)).toEqual([]);
  });
});

describe('the first-run checklist', () => {
  it('starts with nothing done', () => {
    expect(firstRunSteps(null).every((step) => !step.done)).toBe(true);
  });

  it('ticks what the workspace has done', () => {
    expect(firstRunSteps(page).map((step) => step.done)).toEqual([true, true, true, true]);
    const fresh = {
      ...page,
      environments: 0,
      counts: { ...page.counts, integrations: 1, no_provider_contract: 1, verified: 0 },
    };
    expect(firstRunSteps(fresh).map((step) => step.done)).toEqual([true, false, false, false]);
  });
});

describe('the network view', () => {
  it('draws every pacticipant of the page around the busiest one (ties by handle)', () => {
    const network = integrationsNetwork(page.integrations)!;
    expect(network.centre).toBe('billing-service');
    expect(network.pacticipants[0]).toEqual({ slug: 'billing-service', name: 'Billing Service', distance: 0 });
    expect(network.pacticipants).toHaveLength(8);
    expect(network.integrations).toHaveLength(6);
    const failing = network.integrations.find((i) => i.provider.slug === 'billing-service');
    expect(failing?.verdict).toBe('failed');
  });

  it('puts a pacticipant not connected to the centre one hop further out', () => {
    const network = integrationsNetwork(page.integrations)!;
    const furthest = Math.max(...network.pacticipants.map((p) => p.distance));
    expect(network.pacticipants.find((p) => p.slug === 'checkout')?.distance).toBe(furthest);
  });

  it('is nothing for no rows', () => {
    expect(integrationsNetwork([])).toBeNull();
  });
});

describe('"Start something"', () => {
  it('names only `apiome pact` verbs the CLI registers', () => {
    const cli = join(__dirname, '..', '..', 'apiome-cli', 'src', 'apiome_cli', 'commands');
    const source = readFileSync(join(cli, 'pact.py'), 'utf8') + readFileSync(join(cli, 'pact_broker.py'), 'utf8');
    const verbs = new Set([
      ...[...source.matchAll(/@app\.command\("([a-z-]+)"\)/g)].map((m) => m[1]),
      ...[...source.matchAll(/^\s+\("([a-z-]+)", [a-z_]+\),$/gm)].map((m) => m[1]),
    ]);
    const used = WAYS_IN.flatMap((group) => group.ways)
      .filter((way) => way.command)
      .map((way) => /^apiome pact ([a-z-]+)/.exec(way.command ?? '')?.[1]);
    expect(verbs.size).toBeGreaterThan(0);
    for (const verb of used) expect(verbs).toContain(verb);
  });

  it('opens a screen for every entry point now that PFX-8 is complete (#7297)', () => {
    expect(WAYS_IN.flatMap((group) => group.ways).filter((way) => !way.route).map((way) => way.id)).toEqual([]);
  });

  it('gives every entry point a screen or a command, never neither', () => {
    for (const way of WAYS_IN.flatMap((group) => group.ways)) {
      expect(Boolean(way.route) !== Boolean(way.command)).toBe(true);
    }
  });
});
