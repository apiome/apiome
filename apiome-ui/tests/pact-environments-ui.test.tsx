/**
 * The **Environments** pages — PFX-5.7 (#6951).
 *
 * Dashboard:
 * * the grid of pacticipants × environments with each version deployed (and its instance) and each
 *   release, and the environments; axe passes;
 * * an empty workspace shows the CLI commands; a refused read offers **Try again**.
 *
 * Environment page:
 * * the overview, what is deployed and released now, and the deployment history; axe passes;
 * * the **Pacticipant** filter narrows the history, **Load more** reads the next page;
 * * an unknown environment says so; a refused history read offers **Try again** on its own.
 *
 * Deploy simulator:
 * * an address naming a whole question is asked straight away: the verdict, what it replaces,
 *   each counterpart version before → after with its effect, the CLI commands; axe passes;
 * * the form checks what is missing, writes the address and asks; versions not checked are listed
 *   with the reason; REST's refusal is shown with **Try again**.
 *
 * `A11Y_FIXTURE_DUMP=1` writes the docs-screenshot fixtures `pact-environments`,
 * `pact-environment-detail` and `pact-deploy-simulator`.
 */

import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { axe } from 'jest-axe';
import 'jest-axe/extend-expect';

jest.mock('next/navigation', () => ({ useRouter: () => ({ push: jest.fn(), replace: jest.fn() }) }));
jest.mock('next/link', () => ({
  __esModule: true,
  default: ({ children, href, ...props }: { children: React.ReactNode; href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

import fixture from './fixtures/pact-environments.json';
import EnvironmentsClient from '../src/app/components/ade/pactEnvironments/EnvironmentsClient';
import EnvironmentDetailClient from '../src/app/components/ade/pactEnvironments/EnvironmentDetailClient';
import DeploySimulatorClient from '../src/app/components/ade/pactEnvironments/DeploySimulatorClient';
import { liveMarkup, writeA11yFixture } from './helpers/a11y-fixture-dump';

const AXE_OPTIONS = { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } };
const TOPOLOGY = '/api/pact/environment-topology';
const HISTORY = '/api/pact/environments/production/deployments';
const SIMULATE = '/api/pact/environments/production/simulate';

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
    const { status, body } = key ? answers[key]() : { status: 404, body: { success: false, error: 'not found' } };
    return { ok: status < 400, status, json: async () => body } as Response;
  }) as unknown as typeof fetch;
}

beforeEach(() => {
  calls = [];
  answers = {
    [TOPOLOGY]: () => ({ status: 200, body: fixture.topology }),
    [HISTORY]: () => ({ status: 200, body: fixture.history }),
    [`${HISTORY}?cursor=17`]: () => ({
      status: 200,
      body: {
        ...fixture.history,
        deployments: [{ ...fixture.history.deployments[3], uuid: 'd0000000-0000-4000-8000-000000000001', version: '2.1.0' }],
        nextCursor: null,
      },
    }),
    [`${HISTORY}?pacticipant=ledger-api`]: () => ({
      status: 200,
      body: { ...fixture.history, deployments: [fixture.history.deployments[1]], nextCursor: null },
    }),
    [SIMULATE]: () => ({ status: 200, body: fixture.simulation }),
    '/api/pact/pacticipants': () => ({
      status: 200,
      body: {
        pacticipants: [
          { id: 'p-1', slug: 'ledger-api', name: 'Ledger API', labels: [] },
          { id: 'p-2', slug: 'billing-service', name: 'Billing Service', labels: [] },
        ],
        next_cursor: null,
      },
    }),
    '/api/pact/pacticipants/ledger-api/versions': () => ({
      status: 200,
      body: { versions: [{ number: fixture.simulation.version, branches: [], tags: [] }], next_cursor: null },
    }),
  };
  installFetch();
  window.history.replaceState(null, '', '/');
});

describe('Environments dashboard', () => {
  it('lays out every pacticipant in every environment, and the environments', async () => {
    const { container } = render(<EnvironmentsClient />);
    const grid = await screen.findByTestId('penv-grid');
    expect(screen.getByTestId('penv-count')).toHaveTextContent('3 environments');
    expect(within(grid).getByRole('link', { name: 'Production' })).toHaveAttribute(
      'href',
      '/ade/dashboard/pacts/environments/production',
    );
    const ledger = within(grid).getByTestId('penv-row-ledger-api');
    expect(ledger).toHaveTextContent('3f2a9c1b7e6d');
    expect(ledger).toHaveTextContent('9c8b7a6f5e4d');
    expect(within(ledger).getByRole('link', { name: 'Ledger API' })).toHaveAttribute(
      'href',
      '/ade/dashboard/pacts/pacticipants/ledger-api',
    );
    expect(within(grid).getByTestId('penv-row-reporting-job')).toHaveTextContent('1.4.2 · eu-west');
    expect(within(grid).getByTestId('penv-row-mobile-app')).toHaveTextContent('5.2.0 · released');
    const list = screen.getByTestId('penv-environments');
    expect(within(list).getByTestId('penv-env-production')).toHaveTextContent('Production');
    expect(within(list).getByTestId('penv-env-production')).toHaveTextContent('Yes');
    expect(within(list).getByTestId('penv-env-qa')).toHaveTextContent('qa00No');
    expect(screen.queryByTestId('penv-truncated')).toBeNull();
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
    writeA11yFixture('pact-environments', liveMarkup(container.firstElementChild!));
  });

  it('says when the topology was cut short', async () => {
    answers[TOPOLOGY] = () => ({ status: 200, body: { ...fixture.topology, truncated: true } });
    render(<EnvironmentsClient />);
    expect(await screen.findByTestId('penv-truncated')).toHaveTextContent('more than 2000');
  });

  it('shows the CLI commands for an empty workspace, and Try again for a refused read', async () => {
    answers[TOPOLOGY] = () => ({ status: 200, body: { environments: [], truncated: false } });
    const { unmount } = render(<EnvironmentsClient />);
    expect(await screen.findByTestId('penv-empty')).toHaveTextContent('apiome pact create-environment');
    unmount();
    answers[TOPOLOGY] = () => ({ status: 403, body: { success: false, error: 'Permission denied' } });
    render(<EnvironmentsClient />);
    expect(await screen.findByText('Permission denied')).toBeInTheDocument();
    answers[TOPOLOGY] = () => ({ status: 200, body: fixture.topology });
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByTestId('penv-grid')).toBeInTheDocument();
  });
});

describe('Environment page', () => {
  it('shows the overview, what runs there now and the deployment history', async () => {
    const { container } = render(<EnvironmentDetailClient name="production" />);
    const facts = await screen.findByTestId('penv-facts');
    expect(facts).toHaveTextContent('Nameproduction');
    expect(facts).toHaveTextContent('Contract requiredYes');
    const deployed = screen.getByTestId('penv-deployed');
    expect(within(deployed).getAllByRole('row')).toHaveLength(5);
    expect(deployed).toHaveTextContent('us-east');
    expect(screen.getByTestId('penv-released')).toHaveTextContent('Mobile App5.2.0');
    expect(screen.getByTestId('penv-simulate')).toHaveAttribute(
      'href',
      '/ade/dashboard/pacts/environments/production/simulate',
    );
    const history = await screen.findByTestId('penv-history-table');
    const replaced = within(history).getByTestId('penv-history-d0000000-0000-4000-8000-000000000002');
    expect(replaced).toHaveTextContent('Replaced');
    expect(replaced).toHaveTextContent('2026-11-24 09:30 UTC');
    expect(within(history).getByTestId('penv-history-d0000000-0000-4000-8000-000000000005')).toHaveTextContent('Deployed');
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
    writeA11yFixture('pact-environment-detail', liveMarkup(container.firstElementChild!));
  });

  it('narrows the history by pacticipant and loads more', async () => {
    render(<EnvironmentDetailClient name="production" />);
    await screen.findByTestId('penv-history-table');
    fireEvent.click(screen.getByTestId('penv-history-more'));
    await waitFor(() => expect(screen.getAllByText('2.1.0').length).toBeGreaterThan(0));
    expect(calls).toContain(`${HISTORY}?cursor=17`);
    expect(screen.queryByTestId('penv-history-more')).toBeNull();
    fireEvent.change(screen.getByTestId('penv-history-filter'), { target: { value: 'ledger-api' } });
    await waitFor(() => expect(calls).toContain(`${HISTORY}?pacticipant=ledger-api`));
    await waitFor(() => expect(within(screen.getByTestId('penv-history-table')).getAllByRole('row')).toHaveLength(2));
  });

  it('says when there is no such environment', async () => {
    render(<EnvironmentDetailClient name="nowhere" />);
    expect(await screen.findByText('No such environment')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'All environments' })).toHaveAttribute('href', '/ade/dashboard/pacts/environments');
  });

  it('retries a refused history read on its own', async () => {
    answers[HISTORY] = () => ({ status: 500, body: { success: false, error: 'Database busy' } });
    render(<EnvironmentDetailClient name="production" />);
    expect(await screen.findByText('Database busy')).toBeInTheDocument();
    expect(screen.getByTestId('penv-facts')).toBeInTheDocument();
    answers[HISTORY] = () => ({ status: 200, body: fixture.history });
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByTestId('penv-history-table')).toBeInTheDocument();
  });

  it('shows the record-deployment command for an empty environment', async () => {
    answers['/api/pact/environments/qa/deployments'] = () => ({
      status: 200,
      body: { ...fixture.history, deployments: [], nextCursor: null },
    });
    render(<EnvironmentDetailClient name="qa" />);
    expect(await screen.findByTestId('penv-deployed-empty')).toHaveTextContent('--environment qa');
    expect(await screen.findByTestId('penv-history-empty')).toHaveTextContent('No deployment has been recorded here yet.');
  });
});

describe('Deploy simulator', () => {
  const question = `pacticipant=ledger-api&version=${fixture.simulation.version}`;

  it('asks the question in the address and explains the answer', async () => {
    const { container } = render(<DeploySimulatorClient name="production" initialQuery={question} />);
    expect(await screen.findByTestId('psim-headline')).toHaveTextContent('Deployable');
    expect(calls).toContain(`${SIMULATE}?${question}`);
    expect(screen.getByTestId('psim-replaces')).toHaveTextContent(
      'Would replace Ledger API 3f2a9c1b7e6d4a5b8c9d0e1f2a3b4c5d6e7f8a9b in production (the unnamed instance).',
    );
    expect(screen.getByTestId('psim-summary')).toHaveTextContent('1 clears · 2 no change');
    const cleared = screen.getByTestId('psim-impact-billing-service-2.4.0');
    expect(cleared).toHaveTextContent('In staging');
    expect(cleared).toHaveTextContent('Not deployable');
    expect(within(cleared).getByTestId('psim-effect')).toHaveTextContent('Clears');
    expect(screen.getByTestId('psim-impact-billing-service-2.3.1')).toHaveTextContent('Running in production');
    expect(screen.getByTestId('psim-impact-mobile-app-5.3.0')).toHaveTextContent('Not known yet');
    expect(screen.queryByTestId('psim-not-checked')).toBeNull();
    expect(screen.getByTestId('psim-cli')).toHaveTextContent('apiome pact record-deployment');
    expect(screen.getByLabelText('Pacticipant')).toHaveValue('ledger-api');
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
    writeA11yFixture('pact-deploy-simulator', liveMarkup(container.firstElementChild!));
  });

  it('checks the form, writes the address and asks; lists what was not checked', async () => {
    answers[SIMULATE] = () => ({
      status: 200,
      body: { ...fixture.simulation, notChecked: fixture.notChecked, impacts: [], summary: {} },
    });
    render(<DeploySimulatorClient name="production" initialQuery="" />);
    expect(screen.getByText('Try a deployment before you make it')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Simulate' }));
    expect(screen.getByTestId('psim-problem')).toHaveTextContent('Name the pacticipant to deploy.');
    fireEvent.change(screen.getByLabelText('Pacticipant'), { target: { value: 'ledger-api' } });
    fireEvent.change(screen.getByLabelText('Version'), { target: { value: 'p-2' } });
    fireEvent.change(screen.getByLabelText('Application instance (optional)'), { target: { value: 'eu-west' } });
    fireEvent.click(screen.getByRole('button', { name: 'Simulate' }));
    expect(await screen.findByTestId('psim-not-checked')).toHaveTextContent(
      'Only 20 counterpart versions are checked per simulation.',
    );
    expect(screen.getByTestId('psim-no-impacts')).toHaveTextContent('No counterpart version was checked');
    expect(calls).toContain(`${SIMULATE}?pacticipant=ledger-api&version=p-2&applicationInstance=eu-west`);
    expect(window.location.search).toBe('?pacticipant=ledger-api&version=p-2&applicationInstance=eu-west');
    fireEvent.click(screen.getByTestId('psim-recheck'));
    await waitFor(() => expect(calls.filter((url) => url.startsWith(SIMULATE))).toHaveLength(2));
  });

  it('says why an address cannot be asked, and shows REST’s refusal with Try again', async () => {
    const { unmount } = render(<DeploySimulatorClient name="production" initialQuery="pacticipant=a&to=x" />);
    expect(screen.getByTestId('psim-problem')).toHaveTextContent('does not take: to');
    unmount();
    answers[SIMULATE] = () => ({ status: 404, body: { success: false, error: "pacticipant 'ledger-api' has no version 'p-9'" } });
    render(<DeploySimulatorClient name="production" initialQuery="pacticipant=ledger-api&version=p-9" />);
    expect(await screen.findByText("pacticipant 'ledger-api' has no version 'p-9'")).toBeInTheDocument();
    answers[SIMULATE] = () => ({ status: 200, body: fixture.simulation });
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByTestId('psim-headline')).toBeInTheDocument();
  });
});
