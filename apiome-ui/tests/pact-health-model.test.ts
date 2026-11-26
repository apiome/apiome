/**
 * @jest-environment node
 */
/**
 * The shared model of the **Contract health** pages — PFX-6.3 (#6955).
 *
 * * the proxies' query checks: unknown, repeated, empty, malformed parameters are refused naming
 *   them; the pair read takes only `window`;
 * * the REST paths and page routes (the default window left out);
 * * the wording of states, signals, windows, shares and durations;
 * * what the Verification page reads (health by consumer) and a pair's concerns, worst first;
 * * the chart geometry: gaps for buckets without a value, clamped values, a single bucket centred;
 * * the proxies forward checked reads to the right REST path as the signed-in user, and refuse bad
 *   input (400) or a malformed handle (404) without calling REST.
 */

import { jest } from '@jest/globals';
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

import { GET as healthGet } from '../src/app/api/pact/health/route';
import { GET as pairGet } from '../src/app/api/pact/health/[provider]/[consumer]/route';

import {
  CHART,
  DEFAULT_WINDOW,
  HEALTH_PROXY_PATH,
  OVERVIEW_PARAMETERS,
  chartPath,
  chartPoints,
  concerns,
  formatDay,
  formatDuration,
  formatShare,
  healthByConsumer,
  healthProxyPath,
  healthQueryProblem,
  healthRoute,
  healthStateText,
  pairHealthProxyPath,
  pairHealthRoute,
  readWindow,
  signalLabel,
  signalStatusText,
  type HealthOverview,
} from '../lib/pact-health';
import fixture from './fixtures/pact-health.json';

const overview = fixture.overview as HealthOverview;

describe('proxy checks', () => {
  it('accepts the overview parameters', () => {
    const params = new URLSearchParams(
      'window=7d&provider=ledger-api&consumer=orders-ui&state=failing',
    );
    expect(healthQueryProblem(params)).toBeNull();
    expect(healthQueryProblem(new URLSearchParams())).toBeNull();
  });

  it.each([
    ['limit=5', 'Unsupported parameter limit'],
    ['window=7d&window=30d', 'The window parameter is given more than once.'],
    ['state=', 'The state parameter is empty.'],
    ['window=1d', 'The window parameter must be one of 7d, 30d, 90d.'],
    ['state=red', 'The state parameter must be one of failing, degraded, unknown, healthy.'],
    ['provider=Not%20A%20Handle', 'The provider parameter is not a pacticipant handle.'],
  ])('refuses %s naming it', (query, message) => {
    expect(healthQueryProblem(new URLSearchParams(query))).toContain(message);
  });

  it('lets the pair read take only the window', () => {
    expect(healthQueryProblem(new URLSearchParams('window=90d'), ['window'])).toBeNull();
    expect(healthQueryProblem(new URLSearchParams('state=failing'), ['window'])).toContain(
      'this read accepts window',
    );
  });

  it('forwards the checked parameters in a fixed order', () => {
    const params = new URLSearchParams('state=failing&window=7d');
    expect(healthProxyPath(HEALTH_PROXY_PATH, params, OVERVIEW_PARAMETERS)).toBe(
      'pact-health?window=7d&state=failing',
    );
    expect(healthProxyPath(HEALTH_PROXY_PATH, new URLSearchParams(), OVERVIEW_PARAMETERS)).toBe(
      'pact-health',
    );
    expect(pairHealthProxyPath('ledger-api', 'orders-ui')).toBe(
      'pact-health/providers/ledger-api/consumers/orders-ui',
    );
  });
});

describe('routes', () => {
  it('leaves the default window out of the address', () => {
    expect(healthRoute()).toBe('/ade/dashboard/pacts/health');
    expect(healthRoute({ window: DEFAULT_WINDOW, state: 'failing' })).toBe(
      '/ade/dashboard/pacts/health?state=failing',
    );
    expect(healthRoute({ window: '90d' })).toBe('/ade/dashboard/pacts/health?window=90d');
    expect(pairHealthRoute('ledger-api', 'orders-ui')).toBe(
      '/ade/dashboard/pacts/health/ledger-api/orders-ui',
    );
    expect(pairHealthRoute('ledger-api', 'orders-ui', '7d')).toBe(
      '/ade/dashboard/pacts/health/ledger-api/orders-ui?window=7d',
    );
  });

  it('reads an unknown window from the address as the default', () => {
    expect(readWindow('7d')).toBe('7d');
    expect(readWindow('1y')).toBe(DEFAULT_WINDOW);
    expect(readWindow(null)).toBe(DEFAULT_WINDOW);
  });
});

describe('wording', () => {
  it('names states, signal statuses and signals, falling back for unknown values', () => {
    expect(healthStateText('failing')).toMatchObject({ label: 'Failing', variant: 'danger' });
    expect(healthStateText('bogus').label).toBe('Unknown');
    expect(signalStatusText('warn')).toEqual({ label: 'Warning', variant: 'warn' });
    expect(signalStatusText('unknown').label).toBe('No evidence');
    expect(signalLabel('republish-request')).toBe('Re-publish request');
    expect(signalLabel('something-new')).toBe('something-new');
  });

  it('formats shares, durations and days', () => {
    expect(formatShare(0.956)).toBe('96%');
    expect(formatShare(null)).toBe('—');
    expect(formatDuration(850)).toBe('850 ms');
    expect(formatDuration(2400)).toBe('2.4 s');
    expect(formatDuration(90_000)).toBe('1.5 min');
    expect(formatDuration(null)).toBe('—');
    expect(formatDuration(-1)).toBe('—');
    expect(formatDay('2026-11-26T00:00:00+00:00')).toBe('2026-11-26');
    expect(formatDay('not a date')).toBe('—');
  });
});

describe('reading', () => {
  it('maps a provider overview by consumer', () => {
    const byConsumer = healthByConsumer(overview);
    expect(Object.keys(byConsumer).sort()).toEqual(['billing-service', 'orders-ui']);
    expect(healthByConsumer(null)).toEqual({});
  });

  it('lists a pair’s concerns failing first, then warnings', () => {
    const failing = overview.pairs[0];
    expect(concerns(failing).map((component) => component.status)).toEqual([
      'fail',
      'fail',
      'fail',
      'warn',
    ]);
    expect(concerns(overview.pairs[2])).toEqual([]);
  });
});

describe('chart geometry', () => {
  it('leaves buckets without a value out, so the line has gaps', () => {
    const points = chartPoints([1, null, 0.5, 0.5], 1);
    expect(points.map((point) => point.index)).toEqual([0, 2, 3]);
    expect(points[0]).toMatchObject({ x: CHART.padX, y: CHART.padY });
    expect(points[2].x).toBe(CHART.width - CHART.padX);
    expect(chartPath(points)).toMatch(/^M\S+ \S+ M\S+ \S+ L\S+ \S+$/);
  });

  it('clamps values to the scale and centres a single bucket', () => {
    const [only] = chartPoints([5], 1);
    expect(only.x).toBe(CHART.width / 2);
    expect(only.y).toBe(CHART.padY);
    expect(chartPoints([0], 0)[0].y).toBe(CHART.height - CHART.padY);
    expect(chartPath([])).toBe('');
  });
});

describe('the proxies', () => {
  const req = (url: string) => new NextRequest(new URL(url, 'http://ui'));
  const ctx = (provider: string, consumer: string) => ({
    params: Promise.resolve({ provider, consumer }),
  });

  beforeEach(() => {
    forwarded.length = 0;
  });

  it('forwards the overview and a pair to their REST paths', async () => {
    await healthGet(req('/api/pact/health?state=failing&window=7d&provider=ledger-api'));
    await healthGet(req('/api/pact/health'));
    await pairGet(
      req('/api/pact/health/ledger-api/orders-ui?window=90d'),
      ctx('ledger-api', 'orders-ui'),
    );
    const rest = 'http://rest/v1/tenants/acme';
    expect(forwarded).toEqual([
      `${rest}/pact-health?window=7d&provider=ledger-api&state=failing`,
      `${rest}/pact-health`,
      `${rest}/pact-health/providers/ledger-api/consumers/orders-ui?window=90d`,
    ]);
  });

  it('refuses bad input without calling REST', async () => {
    const answers = [
      await healthGet(req('/api/pact/health?window=1d')),
      await healthGet(req('/api/pact/health?cursor=2')),
      await pairGet(
        req('/api/pact/health/ledger-api/orders-ui?state=failing'),
        ctx('ledger-api', 'orders-ui'),
      ),
    ];
    expect(answers.map((answer) => answer.status)).toEqual([400, 400, 400]);
    expect(((await answers[1].json()) as { error: string }).error).toContain(
      'Unsupported parameter cursor',
    );
    const missing = await pairGet(
      req('/api/pact/health/Bad%20Handle/orders-ui'),
      ctx('Bad Handle', 'orders-ui'),
    );
    expect(missing.status).toBe(404);
    expect(forwarded).toEqual([]);
  });
});
