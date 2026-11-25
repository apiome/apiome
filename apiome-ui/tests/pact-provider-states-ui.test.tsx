/**
 * The **Provider states** page — PFX-3.3 (#6933).
 *
 * * **Check**: unregistered states come first and read "Not registered"; each problem reads as a
 *   badge and a sentence naming the interaction; the panel says "Not ready" while something
 *   blocks; registered states no pact names are listed.
 * * **Registered states**: parameters, default setup and each target's override in one line each;
 *   an empty registry says what happens until states are registered.
 * * **Page**: the first provider is selected and both reads load; another provider loads its own;
 *   an empty workspace says how providers appear; a failed read offers a retry.
 *
 * The fixture is the real REST check builder's output over the verifier's three fixture pacts
 * (`tests/fixtures/pact-provider-states.json`). `A11Y_FIXTURE_DUMP=1` writes the docs-screenshot
 * fixture `pact-provider-states`.
 */

import React from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { axe } from 'jest-axe';
import 'jest-axe/extend-expect';

jest.mock('next/link', () => ({
  __esModule: true,
  default: ({ children, href, ...props }: { children: React.ReactNode; href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

import fixture from './fixtures/pact-provider-states.json';
import ProviderStatesClient from '../src/app/components/ade/pactProviderStates/ProviderStatesClient';
import {
  ProviderStateCheck,
  RegisteredStates,
} from '../src/app/components/ade/pactProviderStates/ProviderStatesPanels';
import type { ProviderOption, ProviderState, StateCheckResponse } from '../lib/pact-provider-states';
import { writeA11yFixture } from './helpers/a11y-fixture-dump';

const AXE_OPTIONS = { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } };
const PROVIDERS = fixture.providers as ProviderOption[];
const STATES = fixture.states as unknown as ProviderState[];
const CHECK = fixture.check as unknown as StateCheckResponse;

// --- the panels -------------------------------------------------------------------------------

describe('ProviderStateCheck', () => {
  it('lists unregistered states first, each problem with its badge and sentence', () => {
    render(<ProviderStateCheck check={CHECK} />);
    const panel = screen.getByTestId('pps-check');
    expect(within(panel).getByText('Not ready')).toBeInTheDocument();
    expect(screen.getByTestId('pps-statement')).toHaveTextContent(
      '1 problem would hold interactions back on ledger-staging. 1 warning to review.',
    );
    const entries = within(screen.getByRole('list', { name: 'Provider states the pacts name' })).getAllByRole(
      'listitem',
      {
        name: undefined,
      },
    );
    expect(entries[0]).toHaveAttribute('data-registered', 'false');
    expect(entries[0]).toHaveTextContent('the ledger has entries');
    expect(entries[0]).toHaveTextContent('Not registered');

    const blocking = within(screen.getByRole('list', { name: 'Problems with the ledger has entries' })).getByRole(
      'listitem',
    );
    expect(blocking).toHaveAttribute('data-severity', 'blocking');
    expect(blocking).toHaveTextContent('Blocks');
    expect(blocking).toHaveTextContent('provider-state-not-registered');

    const warning = within(screen.getByRole('list', { name: 'Problems with invoice 1042 exists' })).getByRole(
      'listitem',
    );
    expect(warning).toHaveTextContent('Warning');
    expect(warning).toHaveTextContent('billing-service · a request for invoice 1042');
    expect(screen.getByText(/Recorded fixture · target override/)).toBeInTheDocument();
    expect(screen.getByTestId('pps-unused')).toHaveTextContent('an archived invoice exists');
  });

  it('reads ready when nothing blocks', () => {
    render(<ProviderStateCheck check={{ ...CHECK, ready: true, blocking: 0, warnings: 0, states: [], unused: [] }} />);
    expect(screen.getByText('Ready')).toBeInTheDocument();
    expect(screen.getByTestId('pps-statement')).toHaveTextContent(
      'None of the 3 selected pacts names a provider state.',
    );
  });
});

describe('RegisteredStates', () => {
  it('shows parameters, the default setup and each override', () => {
    render(<RegisteredStates states={STATES} />);
    const invoice = screen.getByText('invoice 1042 exists').closest('li') as HTMLElement;
    expect(invoice).toHaveTextContent('Parameterscurrency = "EUR"');
    expect(invoice).toHaveTextContent('SetupState-change call · POST /_pact/provider-states');
    expect(invoice).toHaveTextContent('On ledger-stagingRecorded fixture · 1 request');
    const archived = screen.getByText('an archived invoice exists').closest('li') as HTMLElement;
    expect(archived).toHaveTextContent('No parameters');
    expect(archived).toHaveTextContent('no teardown');
  });

  it('says what happens until states are registered', () => {
    render(<RegisteredStates states={[]} />);
    expect(screen.getByText(/interactions that name a state are skipped/)).toBeInTheDocument();
  });
});

// --- the page ---------------------------------------------------------------------------------

describe('ProviderStatesClient', () => {
  let routes: Record<string, () => { status: number; body: unknown }>;

  beforeEach(() => {
    routes = {
      '/api/pact-provider-states': () => ({
        status: 200,
        body: { pacticipants: PROVIDERS, count: 3, has_more: false },
      }),
      '/api/pact-provider-states/billing-service': () => ({ status: 200, body: [] }),
      '/api/pact-provider-states/billing-service/check': () => ({
        status: 200,
        body: {
          ...CHECK,
          provider: 'billing-service',
          pacts: 0,
          states: [],
          unused: [],
          ready: true,
          blocking: 0,
          warnings: 0,
        },
      }),
      '/api/pact-provider-states/ledger-api': () => ({ status: 200, body: STATES }),
      '/api/pact-provider-states/ledger-api/check': () => ({ status: 200, body: CHECK }),
    };
    global.fetch = jest.fn(async (input: RequestInfo | URL) => {
      const route = routes[String(input)];
      const { status, body } = route ? route() : { status: 404, body: { success: false, error: 'not found' } };
      return { ok: status < 400, status, json: async () => body } as Response;
    }) as unknown as typeof fetch;
  });

  it('selects the first provider and loads both reads', async () => {
    render(<ProviderStatesClient />);
    expect(await screen.findByTestId('pps-registered')).toBeInTheDocument();
    expect(screen.getByTestId('pps-provider-billing-service')).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByTestId('pps-statement')).toHaveTextContent('nothing to check');
  });

  it('loads another provider when it is chosen, and passes axe', async () => {
    const { container } = render(<ProviderStatesClient />);
    await screen.findByTestId('pps-registered');
    fireEvent.click(screen.getByTestId('pps-provider-ledger-api'));
    expect(await screen.findByText('the ledger has entries')).toBeInTheDocument();
    expect(screen.getByTestId('pps-provider-ledger-api')).toHaveAttribute('aria-pressed', 'true');
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
    writeA11yFixture('pact-provider-states', container.innerHTML);
  });

  it('says how providers appear in an empty workspace', async () => {
    routes['/api/pact-provider-states'] = () => ({
      status: 200,
      body: { pacticipants: [], count: 0, has_more: false },
    });
    render(<ProviderStatesClient />);
    expect(await screen.findByText('No providers yet')).toBeInTheDocument();
  });

  it('offers a retry when the providers or the states cannot be read', async () => {
    routes['/api/pact-provider-states'] = () => ({ status: 403, body: { success: false, error: 'Permission denied' } });
    render(<ProviderStatesClient />);
    expect(await screen.findByText('Permission denied')).toBeInTheDocument();
    routes['/api/pact-provider-states'] = () => ({ status: 200, body: { pacticipants: PROVIDERS, count: 3 } });
    routes['/api/pact-provider-states/billing-service'] = () => ({
      status: 503,
      body: { success: false, error: 'REST down' },
    });
    fireEvent.click(screen.getByRole('button', { name: /try again/i }));
    expect(await screen.findByText('REST down')).toBeInTheDocument();
    routes['/api/pact-provider-states/billing-service'] = () => ({ status: 200, body: [] });
    fireEvent.click(screen.getByRole('button', { name: /try again/i }));
    expect(await screen.findByTestId('pps-registered')).toBeInTheDocument();
  });
});
