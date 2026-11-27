/**
 * The **Contracts** landing and the area's tab row — PFX-8.1 (#7298).
 *
 * Landing (`docs/mockups/contracts/overview.html`, Notes → States):
 * * populated: the tab row with Overview active, one status strip (the failing chip open), the
 *   facts line, every integration worst first with its kind, verdict, shared environments and
 *   when it was verified, a row menu, and "Start something"; header obeys the action cap; axe passes;
 * * read-only (no `pacts:create`): no header actions and no "Start something"; table and strip stay;
 * * empty workspace: no strip, no facts line, an empty table and the first-run checklist;
 * * loading: skeleton rows, never a spinner; error: one banner with **Try again**, which re-reads;
 * * search, chips, page and view go into the address; anything unusable in it is reported;
 * * an action with no screen yet opens its command; the network view draws the page's integrations.
 *
 * Tab row: every Contracts page's header draws it with its own tab active (a source check over every
 * page client, and a render of the shared component).
 *
 * `A11Y_FIXTURE_DUMP=1` writes the docs-screenshot fixtures `pact-overview` and `pact-overview-empty`.
 */

import React from 'react';
import { readdirSync, readFileSync, statSync } from 'fs';
import { join } from 'path';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
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

import fixture from './fixtures/pact-overview.json';
import health from './fixtures/pact-health.json';
import PactOverviewClient from '../src/app/components/ade/pactOverview/PactOverviewClient';
import { ContractsTabs } from '../src/app/components/ade/pactOverview/ContractsTabs';
import { CONTRACTS_TABS, readOverviewQuery, type PactIntegrationsPage } from '../lib/pact-overview';
import { countHeaderActions, pageGateViolations } from './helpers/page-gates';
import { liveMarkup, writeA11yFixture } from './helpers/a11y-fixture-dump';

const AXE_OPTIONS = { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } };
const INTEGRATIONS = '/api/pact/integrations';
const EDITOR = { is_admin: false, permissions: ['pacts:view', 'pacts:create'] };
const VIEWER = { is_admin: false, permissions: ['pacts:view'] };

type Answer = { status: number; body: unknown } | Promise<never>;
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
    const answer = key ? answers[key]() : { status: 404, body: { success: false, error: 'not found' } };
    const { status, body } = await answer;
    return { ok: status < 400, status, json: async () => body } as Response;
  }) as unknown as typeof fetch;
}

/** Answer as a role. */
function as(role: typeof EDITOR) {
  answers['/api/access/permissions/me'] = () => ({ status: 200, body: { success: true, data: role } });
}

function emptyPage(): PactIntegrationsPage {
  const base = fixture.page as unknown as PactIntegrationsPage;
  return {
    ...base,
    integrations: [],
    total: 0,
    pacticipants: 0,
    environments: 0,
    counts: Object.fromEntries(Object.keys(base.counts).map((key) => [key, 0])) as PactIntegrationsPage['counts'],
    attention: { failing: [], stale: [], no_provider_contract: [], pending: [] },
  };
}

beforeEach(() => {
  replace.mockReset();
  calls = [];
  window.localStorage.clear();
  window.sessionStorage.clear();
  answers = {
    [INTEGRATIONS]: () => ({ status: 200, body: fixture.page }),
    '/api/pact/health': () => ({ status: 200, body: health.overview }),
  };
  as(EDITOR);
  installFetch();
});

const open = (query: Record<string, string> = {}) =>
  render(<PactOverviewClient query={readOverviewQuery(query)} />);

describe('Contracts landing', () => {
  it('shows the strip, facts, every integration worst first and the ways in, and passes axe', async () => {
    const { container } = open();
    await screen.findByTestId('ctx-count');
    const table = screen.getByTestId('ctx-integrations-table');
    await screen.findByTestId('ctx-publish');

    // The tab row, Overview active.
    const tabs = screen.getByTestId('contracts-tabs');
    expect(within(tabs).getByRole('link', { name: /Overview/ })).toHaveAttribute('aria-current', 'page');
    expect(within(tabs).getAllByRole('link')).toHaveLength(CONTRACTS_TABS.length);

    // One strip, the failing chip open.
    const strip = screen.getByRole('group', { name: 'Contract status' });
    expect(within(strip).getAllByRole('button').map((chip) => chip.textContent)).toEqual([
      expect.stringContaining('1 failing'),
      expect.stringContaining('1 stale'),
      expect.stringContaining('1 without a provider contract'),
      expect.stringContaining('1 pending'),
    ]);
    expect(screen.getByText('Orders UI → Billing Service failed its newest verification.')).toBeVisible();

    // The facts line.
    expect(screen.getByLabelText('Contracts summary')).toHaveTextContent('6 integrations');
    expect(screen.getByLabelText('Contracts summary')).toHaveTextContent('9 pacticipants');

    // The table.
    const rows = within(table).getAllByRole('row').slice(1);
    expect(rows).toHaveLength(6);
    const failing = screen.getByTestId('ctx-row-orders-ui-billing-service');
    expect(failing).toHaveTextContent('Orders UI');
    expect(failing).toHaveTextContent('Bi-directional');
    expect(failing).toHaveTextContent('Failing');
    expect(failing).toHaveTextContent('staging');
    expect(failing).toHaveTextContent('consumer 3.4.0 · provider 2.7.0');
    const checkout = screen.getByTestId('ctx-row-checkout-payments-api');
    expect(checkout).toHaveTextContent('No provider contract');
    expect(checkout).toHaveTextContent('Pending');
    expect(checkout).toHaveTextContent('never');
    expect(within(failing).getByRole('link', { name: /Orders UI/ })).toHaveAttribute(
      'href',
      '/ade/dashboard/pacts/pacticipants/orders-ui',
    );
    expect(screen.getByTestId('ctx-count')).toHaveTextContent('6 of 6 integrations');
    expect(calls).toContain(`${INTEGRATIONS}?limit=25`);

    // Header: one primary, one secondary, the rest in ⋯.
    const header = container.querySelector('[data-testid="page-header"]')!;
    expect(countHeaderActions(header)).toEqual({ primary: 1, secondary: 1, overflow: 1, selects: [] });
    expect(pageGateViolations(container)).toEqual([]);

    // Start something; the checklist is closed once one integration is verified.
    expect(screen.getByTestId('ctx-ways')).toHaveTextContent('I run the pipeline');
    expect(screen.getByTestId('ctx-way-environments')).toHaveAttribute('href', '/ade/dashboard/pacts/environments');
    expect(screen.queryByTestId('ctx-first-run')).toBeNull();

    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
    writeA11yFixture('pact-overview', liveMarkup(container.firstElementChild!));
  });

  it('hides the header actions and "Start something" from a read-only role', async () => {
    as(VIEWER);
    const { container } = open();
    await screen.findByTestId('ctx-count');
    await waitFor(() => expect(calls).toContain('/api/access/permissions/me'));
    await act(async () => undefined);
    expect(screen.queryByTestId('ctx-publish')).toBeNull();
    expect(screen.queryByTestId('ctx-ways')).toBeNull();
    const header = container.querySelector('[data-testid="page-header"]')!;
    expect(countHeaderActions(header)).toEqual({ primary: 0, secondary: 0, overflow: 0, selects: [] });
    expect(screen.getByRole('group', { name: 'Contract status' })).toBeInTheDocument();
  });

  it('shows an empty workspace with no strip, no facts and the first-run checklist', async () => {
    answers[INTEGRATIONS] = () => ({ status: 200, body: emptyPage() });
    const { container } = open();
    expect(await screen.findByTestId('ctx-empty')).toHaveTextContent('No contracts yet');
    await screen.findByTestId('ctx-ways');
    expect(screen.queryByRole('group', { name: 'Contract status' })).toBeNull();
    expect(screen.queryByLabelText('Contracts summary')).toBeNull();
    const checklist = screen.getByTestId('ctx-first-run');
    expect(checklist).toHaveTextContent('0 of 4 done');
    expect(checklist).toHaveTextContent('Get one integration verified');
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
    writeA11yFixture('pact-overview-empty', liveMarkup(container.firstElementChild!));
  });

  it('draws skeleton rows while the integrations load, never a spinner', async () => {
    answers[INTEGRATIONS] = () => new Promise<never>(() => undefined);
    open();
    expect(await screen.findByTestId('ctx-skeleton')).toBeInTheDocument();
    expect(screen.queryByRole('status', { name: /loading/i })).toBeNull();
  });

  it('shows one banner with Try again when the read fails, and re-reads', async () => {
    answers[INTEGRATIONS] = () => ({ status: 403, body: { success: false, error: 'Permission denied' } });
    const { container } = open();
    const banner = await screen.findByTestId('ctx-error');
    expect(banner).toHaveTextContent('Permission denied');
    expect(pageGateViolations(container)).toEqual([]);
    answers[INTEGRATIONS] = () => ({ status: 200, body: fixture.page });
    fireEvent.click(within(banner).getByRole('button', { name: 'Try again' }));
    expect(await screen.findByTestId('ctx-integrations-table')).toBeInTheDocument();
    expect(calls.filter((url) => url.startsWith(INTEGRATIONS))).toHaveLength(2);
  });

  it('puts the search, a chip, the page and the view into the address', async () => {
    open({ filter: 'stale' });
    await screen.findByTestId('ctx-integrations-table');
    expect(calls).toContain(`${INTEGRATIONS}?filter=stale&limit=25`);
    expect(screen.getByTestId('ctx-chip-stale')).toHaveAttribute('aria-pressed', 'true');

    fireEvent.click(screen.getByTestId('ctx-chip-failing'));
    expect(replace).toHaveBeenLastCalledWith('/ade/dashboard/pacts?filter=failing');

    fireEvent.change(screen.getByTestId('ctx-search'), { target: { value: ' payments ' } });
    fireEvent.submit(screen.getByRole('search'));
    expect(replace).toHaveBeenLastCalledWith('/ade/dashboard/pacts?q=payments&filter=stale');

    fireEvent.click(screen.getByRole('radio', { name: /Network/ }));
    expect(replace).toHaveBeenLastCalledWith('/ade/dashboard/pacts?filter=stale&view=network');
  });

  it('reports what in the address it could not use', async () => {
    open({ filter: 'red', page: 'two' });
    const problems = await screen.findByTestId('ctx-problems');
    expect(problems).toHaveTextContent('There is no filter called “red”');
    expect(problems).toHaveTextContent('Page “two” does not exist');
    expect(calls).toContain(`${INTEGRATIONS}?limit=25`);
  });

  it('says when nothing matches, and offers every integration', async () => {
    answers[INTEGRATIONS] = () => ({
      status: 200,
      body: { ...fixture.page, integrations: [], total: 0, search: 'nothing' },
    });
    open({ q: 'nothing' });
    const none = await screen.findByTestId('ctx-no-match');
    expect(none).toHaveTextContent('Nothing matches “nothing”');
    fireEvent.click(within(none).getByRole('button', { name: 'Show every integration' }));
    expect(replace).toHaveBeenLastCalledWith('/ade/dashboard/pacts');
  });

  it('links Publish a pact to its page and opens the command of an action with no screen yet', async () => {
    open();
    expect(await screen.findByTestId('ctx-publish')).toHaveAttribute('href', '/ade/dashboard/pacts/publish');
    expect(screen.getByTestId('ctx-way-publish-pact')).toHaveAttribute('href', '/ade/dashboard/pacts/publish');
    // PFX-8.6 (#7303): the provider contract has its page now.
    expect(screen.getByTestId('ctx-way-publish-provider-contract')).toHaveAttribute('href', '/ade/dashboard/pacts/provider-contracts/new');

    fireEvent.click(screen.getByTestId('ctx-way-migrate'));
    expect(await screen.findByTestId('ctx-command-dialog')).toHaveTextContent('apiome pact migrate');
  });

  it('draws the page of integrations as a network', async () => {
    open({ view: 'network' });
    expect(await screen.findByTestId('ctx-network')).toBeInTheDocument();
    expect(screen.getByTestId('pact-network-plot')).toBeInTheDocument();
    expect(screen.queryByTestId('ctx-integrations-table')).toBeNull();
  });

  it('pages through the matching integrations', async () => {
    answers[INTEGRATIONS] = () => ({ status: 200, body: { ...fixture.page, total: 60 } });
    open({ page: '2' });
    await screen.findByTestId('ctx-count');
    expect(calls).toContain(`${INTEGRATIONS}?limit=25&offset=25`);
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    expect(replace).toHaveBeenLastCalledWith('/ade/dashboard/pacts?page=3');
    fireEvent.click(screen.getByRole('button', { name: 'Previous' }));
    expect(replace).toHaveBeenLastCalledWith('/ade/dashboard/pacts');
  });

  it('says how many pairs a capped read left out', async () => {
    answers[INTEGRATIONS] = () => ({
      status: 200,
      body: { ...fixture.page, truncated: true, omitted_integrations: 40 },
    });
    open();
    expect(await screen.findByTestId('ctx-count')).toHaveTextContent('40 more are not listed');
  });
});

describe('the Contracts tab row', () => {
  it('marks only the page’s own tab', () => {
    render(<ContractsTabs active="health" />);
    const links = screen.getAllByRole('link');
    expect(links.filter((link) => link.getAttribute('aria-current') === 'page').map((l) => l.textContent)).toEqual([
      'Health',
    ]);
  });

  it('is drawn in the header of every Contracts page, with a real tab active', () => {
    const root = join(__dirname, '..', 'src', 'app', 'components', 'ade');
    const ids = new Set(CONTRACTS_TABS.map((tab) => tab.id));
    const clients = readdirSync(root)
      .filter((dir) => dir.startsWith('pact') && statSync(join(root, dir)).isDirectory())
      .flatMap((dir) => readdirSync(join(root, dir)).map((file) => join(root, dir, file)))
      .filter((file) => file.endsWith('.tsx') && readFileSync(file, 'utf8').includes('<PageHeader'));
    expect(clients.length).toBeGreaterThanOrEqual(22);
    for (const file of clients) {
      const source = readFileSync(file, 'utf8');
      const headers = source.split('<PageHeader').length - 1;
      const tabs = [...source.matchAll(/tabs=\{<ContractsTabs active="([a-z-]+)" \/>\}/g)].map((m) => m[1]);
      expect({ file, tabs: tabs.length }).toEqual({ file, tabs: headers });
      for (const id of tabs) expect(ids).toContain(id);
    }
  });
});
