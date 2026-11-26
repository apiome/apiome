/**
 * The **Network** page — PFX-5.3 (#6947).
 *
 * * The diagram draws every pacticipant and integration; each edge carries its verdict (colour
 *   class, mark and accessible name) and opens the pact; each pacticipant opens its own network;
 *   the key counts the verdicts; the integrations table lists every integration; axe passes.
 * * What the roll-up could not read is said above the diagram.
 * * A refused read shows REST's message with **Try again**; a pacticipant with no pact shows the
 *   publish command.
 *
 * `A11Y_FIXTURE_DUMP=1` writes the docs-screenshot fixture `pact-network`.
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

import fixture from './fixtures/pact-network.json';
import PactNetworkClient from '../src/app/components/ade/pactNetwork/PactNetworkClient';
import type { PactNetwork } from '../lib/pact-network';
import { writeA11yFixture } from './helpers/a11y-fixture-dump';

const AXE_OPTIONS = { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } };
const URL_ = '/api/pact/pacticipants/billing-service/network';
const NETWORK = fixture as PactNetwork;

let answer: () => { status: number; body: unknown };
let calls: string[];

beforeEach(() => {
  calls = [];
  answer = () => ({ status: 200, body: NETWORK });
  global.fetch = jest.fn(async (input: RequestInfo | URL) => {
    calls.push(String(input));
    const { status, body } =
      String(input) === URL_
        ? answer()
        : { status: 404, body: { success: false, error: 'not found' } };
    return { ok: status < 400, status, json: async () => body } as Response;
  }) as unknown as typeof fetch;
});

describe('PactNetworkClient', () => {
  it('draws the network with each integration’s verdict, lists it, and passes axe', async () => {
    const { container } = render(<PactNetworkClient slug="billing-service" />);
    const plot = await screen.findByTestId('pact-network-plot');
    expect(calls).toEqual([URL_]);
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Billing Service network');
    expect(screen.getByTestId('pnx-summary')).toHaveTextContent('7 pacticipants · 6 integrations');

    const group = within(plot).getByRole('group');
    expect(group).toHaveAccessibleName(
      'Network of Billing Service: 7 pacticipants, 6 integrations (3 Verified, 1 Failed, 1 Failed (pending), 1 Not verified yet)',
    );
    for (const p of NETWORK.pacticipants) {
      expect(screen.getByTestId(`network-node-${p.slug}`)).toBeInTheDocument();
    }
    expect(screen.getByTestId('network-node-billing-service')).toHaveAttribute('data-centre');

    const failed = screen.getByTestId('network-edge-mobile-app|billing-service');
    expect(failed).toHaveAttribute('data-verdict', 'failed');
    expect(within(failed).getByRole('link')).toHaveAttribute(
      'href',
      '/ade/dashboard/pacts/pacticipants/mobile-app/pacts/billing-service',
    );
    expect(within(failed).getByRole('link')).toHaveAccessibleName(
      'Mobile App → Billing Service: Failed, consumer version 3.2.0. Open the pact.',
    );
    expect(failed).toHaveTextContent('✕');
    expect(screen.getByTestId('network-edge-billing-service|notification-service')).toHaveAttribute(
      'data-verdict',
      'unverified',
    );
    expect(within(screen.getByTestId('network-node-ledger-api')).getByRole('link')).toHaveAttribute(
      'href',
      '/ade/dashboard/pacts/pacticipants/ledger-api/network',
    );

    const legend = screen.getByTestId('pact-network-legend');
    expect(
      within(legend)
        .getAllByRole('listitem')
        .map((li) => li.textContent),
    ).toEqual(['✓Verified3', '✕Failed1', '!Failed (pending)1', '?Not verified yet1']);
    expect(screen.queryByTestId('pnx-notices')).not.toBeInTheDocument();

    const table = screen.getByTestId('pact-network-table');
    expect(within(table).getAllByRole('row')).toHaveLength(7);
    expect(within(table).getByRole('link', { name: 'Ledger API → Audit Log' })).toHaveAttribute(
      'href',
      '/ade/dashboard/pacts/pacticipants/ledger-api/pacts/audit-log',
    );
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
    writeA11yFixture('pact-network', container.innerHTML);
  });

  it('says what the roll-up could not read', async () => {
    answer = () => ({
      status: 200,
      body: {
        ...NETWORK,
        pacticipants: NETWORK.pacticipants.map((p) =>
          p.slug === 'reporting'
            ? { ...p, gap: 'failed', error: 'Permission denied' }
            : p.slug === 'audit-log'
              ? { ...p, gap: 'not-read' }
              : p,
        ),
      },
    });
    render(<PactNetworkClient slug="billing-service" />);
    const notices = await screen.findByTestId('pnx-notices');
    expect(notices).toHaveTextContent('The pacts of Audit Log were not read');
    expect(notices).toHaveTextContent(
      'The pacts of Reporting (Permission denied) could not be read, so some of their integrations may be missing.',
    );
    expect(screen.getByTestId('network-node-reporting')).toHaveAttribute('data-gap', 'failed');
    expect(
      within(screen.getByTestId('network-node-audit-log')).getByRole('link'),
    ).toHaveAccessibleName(/its pacts were not read/);
  });

  it('shows REST’s refusal with Try again, and reads again', async () => {
    answer = () => ({ status: 403, body: { success: false, error: 'Permission denied' } });
    render(<PactNetworkClient slug="billing-service" />);
    expect(await screen.findByText('The network could not be read')).toBeInTheDocument();
    expect(screen.getByText('Permission denied')).toBeInTheDocument();
    answer = () => ({ status: 200, body: NETWORK });
    fireEvent.click(screen.getByRole('button', { name: /try again/i }));
    expect(await screen.findByTestId('pact-network-plot')).toBeInTheDocument();
    expect(calls).toEqual([URL_, URL_]);
  });

  it('shows the publish command when the pacticipant is in no pact', async () => {
    answer = () => ({
      status: 200,
      body: {
        centre: 'billing-service',
        pacticipants: [{ slug: 'billing-service', name: 'billing-service', distance: 0 }],
        integrations: [],
      },
    });
    const { container } = render(<PactNetworkClient slug="billing-service" />);
    const empty = await screen.findByTestId('pnx-empty');
    expect(empty).toHaveTextContent('No integrations yet');
    expect(screen.getByLabelText('Publish a pact')).toHaveTextContent(
      'apiome pact publish ./pacts',
    );
    expect(within(empty).getByRole('link', { name: 'Back to billing-service' })).toHaveAttribute(
      'href',
      '/ade/dashboard/pacts/pacticipants/billing-service',
    );
    expect(screen.queryByTestId('pact-network-plot')).not.toBeInTheDocument();
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
  });

  it('refreshes', async () => {
    render(<PactNetworkClient slug="billing-service" />);
    await screen.findByTestId('pact-network-plot');
    fireEvent.click(screen.getByRole('button', { name: /refresh/i }));
    await screen.findByTestId('pact-network-plot');
    expect(calls).toEqual([URL_, URL_]);
  });
});
