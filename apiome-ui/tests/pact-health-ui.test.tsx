/**
 * The **Contract health** pages and the health badges of the **Verification** page — PFX-6.3 (#6955).
 *
 * Health page:
 * * the KPI strip and every pair, worst first, with its state, concerns and analytics; each pair
 *   links to its page keeping the window; axe passes;
 * * **Window** and **State** go into the address; the overview is read with them;
 * * an empty list says why (no pacts, or none in the state); a cap says how many are left out; a
 *   refused read offers **Try again**.
 *
 * Pair page:
 * * the state, the newest pact, the metrics, every signal with its reason, the three trend charts
 *   and the trend table (newest first, empty days included); axe passes;
 * * untimed results are said to be left out of the mean duration; an open re-publish request is
 *   linked; **Window** goes into the address; a refused read offers **Try again**.
 *
 * Verification page: each consumer with a health is badged, linked to its pair page; a consumer
 * without one is not.
 *
 * `A11Y_FIXTURE_DUMP=1` writes the docs-screenshot fixtures `pact-health` and `pact-pair-health`.
 */

import React from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { axe } from 'jest-axe';
import 'jest-axe/extend-expect';

const replace = jest.fn();
jest.mock('next/navigation', () => ({ useRouter: () => ({ replace, push: jest.fn() }) }));
jest.mock('next/link', () => ({
  __esModule: true,
  default: ({ children, href, ...props }: { children: React.ReactNode; href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

import fixture from './fixtures/pact-health.json';
import verification from './fixtures/pact-verification.json';
import HealthClient from '../src/app/components/ade/pactHealth/HealthClient';
import PairHealthClient from '../src/app/components/ade/pactHealth/PairHealthClient';
import { StatusTable } from '../src/app/components/ade/pactVerification/VerificationPanels';
import type { PairHealth } from '../lib/pact-health';
import type { VerificationStatusEntry } from '../lib/pact-verification';
import { liveMarkup, writeA11yFixture } from './helpers/a11y-fixture-dump';

const AXE_OPTIONS = { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } };
const HEALTH = '/api/pact/health';
const PAIR = `${HEALTH}/ledger-api/orders-ui`;

type Answer = { status: number; body: unknown };
let answers: Record<string, () => Answer>;
let calls: string[];

/** REST through the proxies: the longest route key the URL starts with answers. */
function installFetch() {
  global.fetch = jest.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    calls.push(url);
    const key = Object.keys(answers)
      .sort((a, b) => b.length - a.length)
      .find((candidate) => url.startsWith(candidate));
    const { status, body } = key
      ? answers[key]()
      : { status: 404, body: { success: false, error: 'not found' } };
    return { ok: status < 400, status, json: async () => body } as Response;
  }) as unknown as typeof fetch;
}

beforeEach(() => {
  replace.mockReset();
  calls = [];
  answers = {
    [HEALTH]: () => ({ status: 200, body: fixture.overview }),
    [PAIR]: () => ({ status: 200, body: fixture.detail }),
  };
  installFetch();
});

describe('Contract health', () => {
  it('lists every pair worst first with its state, concerns and analytics, and passes axe', async () => {
    const { container } = render(<HealthClient window="30d" state={null} />);
    const table = await screen.findByTestId('phx-pairs-table');
    const rows = within(table).getAllByRole('row').slice(1);
    expect(rows.map((row) => within(row).getByTestId('phx-state').textContent)).toEqual([
      'Failing',
      'Degraded',
      'Healthy',
    ]);
    const failing = screen.getByTestId('phx-pair-ledger-api-orders-ui');
    expect(failing).toHaveTextContent('Orders UI → Ledger API');
    expect(failing).toHaveTextContent('Latest verdict');
    expect(failing).toHaveTextContent('64%');
    expect(failing).toHaveTextContent('2.1 s');
    expect(within(failing).getByRole('link', { name: 'Orders UI → Ledger API' })).toHaveAttribute(
      'href',
      '/ade/dashboard/pacts/health/ledger-api/orders-ui',
    );
    expect(screen.getByTestId('phx-pair-inventory-api-orders-ui')).toHaveTextContent('No concerns');
    expect(screen.getByTestId('phx-kpi-failing')).toHaveTextContent('1');
    expect(screen.getByTestId('phx-kpi-pairs')).toHaveTextContent('3');
    expect(calls[0]).toBe(`${HEALTH}?window=30d`);
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
    writeA11yFixture('pact-health', liveMarkup(container.firstElementChild!));
  });

  it('reads with the window and state, and puts a change into the address', async () => {
    render(<HealthClient window="7d" state="failing" />);
    await screen.findByTestId('phx-pairs-table');
    expect(calls[0]).toBe(`${HEALTH}?window=7d&state=failing`);
    fireEvent.change(screen.getByTestId('phx-window'), { target: { value: '90d' } });
    expect(replace).toHaveBeenCalledWith('/ade/dashboard/pacts/health?window=90d&state=failing');
    fireEvent.change(screen.getByTestId('phx-state-filter'), { target: { value: '' } });
    expect(replace).toHaveBeenLastCalledWith('/ade/dashboard/pacts/health?window=7d');
  });

  it('keeps the window in each pair link', async () => {
    render(<HealthClient window="90d" state={null} />);
    const row = await screen.findByTestId('phx-pair-ledger-api-orders-ui');
    expect(within(row).getByRole('link')).toHaveAttribute(
      'href',
      '/ade/dashboard/pacts/health/ledger-api/orders-ui?window=90d',
    );
  });

  it('says why the list is empty', async () => {
    answers[HEALTH] = () => ({ status: 200, body: { ...fixture.overview, pairs: [] } });
    const { unmount } = render(<HealthClient window="30d" state={null} />);
    expect(await screen.findByTestId('phx-pairs-empty')).toHaveTextContent('No pacts yet');
    unmount();
    render(<HealthClient window="30d" state="unknown" />);
    expect(await screen.findByTestId('phx-pairs-empty')).toHaveTextContent('No unknown pairs');
  });

  it('says how many pairs the cap left out', async () => {
    answers[HEALTH] = () => ({
      status: 200,
      body: { ...fixture.overview, truncated: true, omitted_pairs: 12 },
    });
    render(<HealthClient window="30d" state={null} />);
    expect(await screen.findByTestId('phx-truncated')).toHaveTextContent(
      '12 more pairs are not listed',
    );
  });

  it('offers Try again when the health cannot be read', async () => {
    answers[HEALTH] = () => ({ status: 403, body: { success: false, error: 'Permission denied' } });
    render(<HealthClient window="30d" state={null} />);
    expect(await screen.findByText('The contract health could not be read')).toBeInTheDocument();
    expect(screen.getByText(/Permission denied/)).toBeInTheDocument();
    answers[HEALTH] = () => ({ status: 200, body: fixture.overview });
    fireEvent.click(screen.getByRole('button', { name: /Try again/ }));
    expect(await screen.findByTestId('phx-pairs-table')).toBeInTheDocument();
  });
});

describe('Pair health', () => {
  it('shows the state, metrics, every signal, the charts and the trend table, and passes axe', async () => {
    const { container } = render(
      <PairHealthClient provider="ledger-api" consumer="orders-ui" window="7d" />,
    );
    expect(await screen.findByTestId('phx-verdict')).toHaveTextContent('Failing');
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Orders UI → Ledger API');
    expect(screen.getByTestId('phx-metric-runs')).toHaveTextContent('14');
    expect(screen.getByTestId('phx-metric-flips')).toHaveTextContent('6');
    expect(screen.getByTestId('phx-metric-flakiness')).toHaveTextContent('46%');
    const signals = screen.getByTestId('phx-signals');
    expect(within(signals).getAllByRole('listitem')).toHaveLength(6);
    expect(screen.getByTestId('phx-signal-pass-rate')).toHaveTextContent(
      '64% of 14 results passed',
    );
    expect(screen.getByTestId('phx-signal-webhooks')).toHaveTextContent(
      'pact-health-webhooks-failing',
    );
    for (const key of ['pass-rate', 'flakiness', 'duration']) {
      expect(screen.getByTestId(`phx-chart-${key}`).querySelector('svg')).toHaveAttribute(
        'role',
        'img',
      );
    }
    expect(screen.getByTestId('phx-chart-pass-rate').querySelectorAll('circle')).toHaveLength(6);
    const trend = within(screen.getByTestId('phx-trend-table')).getAllByRole('row').slice(1);
    expect(trend).toHaveLength(7);
    expect(trend[0]).toHaveTextContent('2026-11-26');
    expect(trend[3]).toHaveTextContent('2026-11-23');
    expect(trend[3]).toHaveClass('phx-row--empty');
    expect(screen.getByTestId('phx-untimed')).toHaveTextContent(
      'Every result in the window carries its duration.',
    );
    expect(calls[0]).toBe(`${PAIR}?window=7d`);
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
    writeA11yFixture('pact-pair-health', liveMarkup(container.firstElementChild!));
  });

  it('says untimed results are left out, and links an open re-publish request', async () => {
    const degraded = fixture.overview.pairs[1] as PairHealth;
    answers[`${HEALTH}/ledger-api/billing-service`] = () => ({
      status: 200,
      body: { ...fixture.detail, pair: degraded },
    });
    render(<PairHealthClient provider="ledger-api" consumer="billing-service" window="7d" />);
    expect(await screen.findByTestId('phx-untimed')).toHaveTextContent(
      '2 of 3 results carry no duration',
    );
    expect(screen.getByRole('link', { name: 'Open re-publish request' })).toHaveAttribute(
      'href',
      `/ade/dashboard/pacts/republish-requests/${degraded.republish_request_id}`,
    );
  });

  it('puts a window change into the address', async () => {
    render(<PairHealthClient provider="ledger-api" consumer="orders-ui" window="7d" />);
    fireEvent.change(await screen.findByTestId('phx-window'), { target: { value: '30d' } });
    expect(replace).toHaveBeenCalledWith('/ade/dashboard/pacts/health/ledger-api/orders-ui');
  });

  it('offers Try again when the pair cannot be read', async () => {
    answers[PAIR] = () => ({
      status: 404,
      body: { success: false, error: "'orders-ui' has published no pact" },
    });
    render(<PairHealthClient provider="ledger-api" consumer="orders-ui" window="7d" />);
    expect(await screen.findByText("This pair's health could not be read")).toBeInTheDocument();
    expect(screen.getByText(/has published no pact/)).toBeInTheDocument();
  });
});

describe('the Verification page', () => {
  it('badges each consumer with a health and links it to the pair page', () => {
    const entries = verification.status.pacts as unknown as VerificationStatusEntry[];
    const consumer = entries[0].consumer;
    const health = { [consumer]: { ...(fixture.overview.pairs[0] as PairHealth), consumer } };
    render(
      <StatusTable
        entries={entries}
        provider="ledger-api"
        onRerun={() => undefined}
        health={health}
      />,
    );
    const badge = screen.getByTestId(`pvx-health-${consumer}`);
    expect(badge).toHaveTextContent('Failing');
    expect(badge).toHaveAttribute('href', `/ade/dashboard/pacts/health/ledger-api/${consumer}`);
    for (const entry of entries.slice(1)) {
      expect(screen.queryByTestId(`pvx-health-${entry.consumer}`)).not.toBeInTheDocument();
    }
  });
});
