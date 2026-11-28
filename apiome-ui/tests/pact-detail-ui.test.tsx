/**
 * The **Pact** page — PFX-5.2 (#6946).
 *
 * * Overview facts, the verification status (verdict and every provider version), the changes
 *   since the previous different pact, every interaction with its states, request and response
 *   (or message), and the history; axe passes.
 * * Opening another version from the history or from the changes re-reads that version's pact
 *   and keeps the address shareable.
 * * Each section fails and retries on its own; a missing pact shows the publish command; an
 *   unverified pact shows how to verify it; each outcome without a previous pact is said.
 * * An interaction type Apiome does not draw is shown as its JSON with the reason.
 *
 * `A11Y_FIXTURE_DUMP=1` writes the docs-screenshot fixture `pact-detail`.
 */

import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
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

import fixture from './fixtures/pact-detail.json';
import PactDetailClient from '../src/app/components/ade/pactDetail/PactDetailClient';
import { InteractionList } from '../src/app/components/ade/pactDetail/PactPanels';
import { parsePact } from '../lib/pact-detail';
import { writeA11yFixture } from './helpers/a11y-fixture-dump';

const AXE_OPTIONS = { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } };
const BASE = '/api/pact/pacts/ledger-api/billing-service';

type Route = () => { status: number; body: unknown };

let routes: Record<string, Route>;
let calls: string[];

/** Install a fetch that answers by exact URL. */
function installFetch() {
  calls = [];
  global.fetch = jest.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    calls.push(url);
    const route = routes[url];
    const { status, body } = route
      ? route()
      : { status: 404, body: { success: false, error: 'No pact found' } };
    return { ok: status < 400, status, json: async () => body } as Response;
  }) as unknown as typeof fetch;
}

const ok =
  (body: unknown): Route =>
  () => ({ status: 200, body });
const fail =
  (status: number, error: string): Route =>
  () => ({ status, body: { success: false, error } });

const FOUND = {
  outcome: 'found',
  consumerVersion: '1.4.0',
  scanned: 1,
  previous: {
    consumerVersion: '1.3.2',
    sha: fixture.shaB,
    publishedAt: '2026-11-18T09:12:00Z',
    document: fixture.previous,
  },
};

/** The pact of 1.3.2, as REST answers it. */
const PREVIOUS_AS_CURRENT = fixture.previous;

beforeEach(() => {
  routes = {
    [BASE]: ok(fixture.current),
    [`${BASE}/previous`]: ok(FOUND),
    [`${BASE}/history`]: ok(fixture.history),
    [`${BASE}?version=1.3.2`]: ok(PREVIOUS_AS_CURRENT),
    [`${BASE}/previous?version=1.3.2`]: ok({
      outcome: 'first',
      consumerVersion: '1.3.2',
      scanned: 0,
      previous: null,
    }),
  };
  installFetch();
  window.history.replaceState(null, '', '/');
});

describe('PactDetailClient', () => {
  it('shows the overview, verification, changes, interactions and history, and passes axe', async () => {
    const { container } = render(
      <PactDetailClient consumer="billing-service" provider="ledger-api" />,
    );
    const facts = await screen.findByTestId('ppd-facts');
    expect(facts).toHaveTextContent('Consumer version1.4.0');
    expect(facts).toHaveTextContent('Pact versiona3f9c2e417b0');
    expect(facts).toHaveTextContent('SpecificationPact 3.0.0');
    expect(facts).toHaveTextContent('Interactions3 HTTP, 1 message');
    expect(within(facts).getByRole('link', { name: 'Ledger API' })).toHaveAttribute(
      'href',
      '/ade/dashboard/pacts/pacticipants/ledger-api',
    );

    const verifications = await screen.findByTestId('ppd-verifications-table');
    expect(within(verifications).getAllByRole('row')).toHaveLength(3);
    expect(verifications).toHaveTextContent('2.8.0');
    expect(verifications).toHaveTextContent('Pending');
    expect(
      within(screen.getByTestId('ppd-verification')).getAllByTestId('ppd-verdict')[0],
    ).toHaveTextContent('Verified');
    // PFX-5.5: the provider's Verification page, narrowed to this consumer.
    expect(screen.getByTestId('ppd-verification-link')).toHaveAttribute(
      'href',
      '/ade/dashboard/pacts/pacticipants/ledger-api/verification?consumer=billing-service',
    );

    expect(await screen.findByTestId('ppd-diff-summary')).toHaveTextContent(
      '1 added, 1 changed, 1 removed, 2 unchanged',
    );
    const diff = screen.getByTestId('ppd-diff-list');
    expect(diff).toHaveTextContent('Added');
    expect(diff).toHaveTextContent('a request for a missing invoice');
    expect(diff).toHaveTextContent('response.body.amount');
    expect(diff).toHaveTextContent('"120.50" → 120.5');
    expect(diff).toHaveTextContent('Removed');
    expect(diff).toHaveTextContent('a request to refund an invoice');

    const interactions = screen.getByTestId('ppd-interaction-list');
    expect(interactions.querySelectorAll(':scope > li')).toHaveLength(4);
    expect(interactions).toHaveTextContent('GET /invoices/INV-42 → 200');
    expect(interactions).toHaveTextContent('POST /entries?dryRun=false → 201');
    expect(interactions).toHaveTextContent('Given invoice INV-42 exists');
    expect(interactions).toHaveTextContent('{"id":"INV-42"}');
    expect(within(interactions).getByText('New')).toBeInTheDocument();
    expect(within(interactions).getByText('Changed')).toBeInTheDocument();
    expect(interactions).toHaveTextContent('invoices.settled');

    const history = screen.getByTestId('ppd-history-table');
    expect(within(history).getAllByRole('row')).toHaveLength(4);
    expect(screen.getByTestId('ppd-history-1.4.0')).toHaveAttribute('aria-current', 'true');
    expect(screen.getByTestId('ppd-history-1.3.1')).toHaveTextContent('feat/refunds');
    expect(screen.getByTestId('ppd-history-count')).toHaveTextContent('3 versions');

    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
    // Open the first interaction for the screenshot, so its request and response show.
    container.querySelector('details')?.setAttribute('open', '');
    writeA11yFixture('pact-detail', container.innerHTML);
  });

  it('opens another version from the history, and keeps the address shareable', async () => {
    render(<PactDetailClient consumer="billing-service" provider="ledger-api" />);
    const history = await screen.findByTestId('ppd-history-table');
    fireEvent.click(
      within(history).getByRole('button', { name: 'Open the pact of version 1.3.2' }),
    );
    await waitFor(() =>
      expect(screen.getByTestId('ppd-facts')).toHaveTextContent('Consumer version1.3.2'),
    );
    expect(calls).toContain(`${BASE}?version=1.3.2`);
    expect(window.location.search).toBe('?version=1.3.2');
    expect(await screen.findByTestId('ppd-previous-outcome')).toHaveTextContent(
      'first pact of this integration',
    );
    expect(screen.getByTestId('ppd-history-1.3.2')).toHaveAttribute('aria-current', 'true');
  });

  it('opens the previous version from the changes', async () => {
    render(<PactDetailClient consumer="billing-service" provider="ledger-api" />);
    await screen.findByTestId('ppd-diff-list');
    fireEvent.click(
      within(screen.getByTestId('ppd-changes')).getByRole('button', {
        name: 'Open the pact of version 1.3.2',
      }),
    );
    await waitFor(() =>
      expect(screen.getByTestId('ppd-facts')).toHaveTextContent('Consumer version1.3.2'),
    );
  });

  it('opens the version asked for in the address', async () => {
    render(
      <PactDetailClient consumer="billing-service" provider="ledger-api" initialVersion="1.3.2" />,
    );
    expect(await screen.findByTestId('ppd-facts')).toHaveTextContent('Consumer version1.3.2');
    expect(calls).not.toContain(BASE);
    // PFX-8.18 (#7315): the Export page opens on this pact's file.
    expect(screen.getByTestId('ppd-export')).toHaveAttribute(
      'href',
      '/ade/dashboard/pacts/export?kind=file&provider=ledger-api&consumer=billing-service&version=1.3.2',
    );
  });

  it('says each outcome without a previous pact', async () => {
    routes[`${BASE}/previous`] = ok({
      outcome: 'scan-limit',
      consumerVersion: '1.4.0',
      scanned: 20,
      previous: null,
    });
    render(<PactDetailClient consumer="billing-service" provider="ledger-api" />);
    expect(await screen.findByTestId('ppd-previous-outcome')).toHaveTextContent(
      'The 20 versions before this one published this same pact',
    );
    expect(screen.queryByTestId('ppd-diff-summary')).not.toBeInTheDocument();
    expect(screen.queryByText('New')).not.toBeInTheDocument();
  });

  it('keeps the other sections when one cannot be read, and retries it', async () => {
    routes[`${BASE}/previous`] = fail(500, 'An earlier pact could not be read.');
    routes[`${BASE}/history`] = fail(403, 'Permission denied');
    render(<PactDetailClient consumer="billing-service" provider="ledger-api" />);
    expect(await screen.findByText('The previous pact could not be read')).toBeInTheDocument();
    expect(await screen.findByText('The history could not be read')).toBeInTheDocument();
    expect(screen.getByText('The verification results could not be read')).toBeInTheDocument();
    expect(screen.getByTestId('ppd-interaction-list')).toBeInTheDocument();

    routes[`${BASE}/previous`] = ok(FOUND);
    fireEvent.click(
      within(screen.getByTestId('ppd-changes')).getByRole('button', { name: /try again/i }),
    );
    expect(await screen.findByTestId('ppd-diff-list')).toBeInTheDocument();

    routes[`${BASE}/history`] = ok(fixture.history);
    fireEvent.click(
      within(screen.getByTestId('ppd-history')).getByRole('button', { name: /try again/i }),
    );
    expect(await screen.findByTestId('ppd-verifications-table')).toBeInTheDocument();
  });

  it('shows the publish command when the integration has no pact', async () => {
    routes[BASE] = fail(404, 'No pact found');
    render(<PactDetailClient consumer="billing-service" provider="ledger-api" />);
    const empty = await screen.findByTestId('ppd-empty');
    expect(empty).toHaveTextContent('No pact yet');
    expect(empty).toHaveTextContent('apiome pact publish');
    expect(within(empty).getByRole('link', { name: 'Back to billing-service' })).toHaveAttribute(
      'href',
      '/ade/dashboard/pacts/pacticipants/billing-service',
    );
  });

  it('says a pact that cannot be read, and retries it', async () => {
    routes[BASE] = fail(403, 'Permission denied');
    render(<PactDetailClient consumer="billing-service" provider="ledger-api" />);
    expect(await screen.findByText('Permission denied')).toBeInTheDocument();
    routes[BASE] = ok(fixture.current);
    fireEvent.click(screen.getByRole('button', { name: /try again/i }));
    expect(await screen.findByTestId('ppd-facts')).toBeInTheDocument();
  });

  it('shows how to verify a pact nobody has verified yet', async () => {
    const unverified = JSON.parse(JSON.stringify(fixture.history));
    unverified.matrix = unverified.matrix.map((row: Record<string, unknown>) => ({
      ...row,
      verificationResult: null,
    }));
    routes[`${BASE}/history`] = ok(unverified);
    render(<PactDetailClient consumer="billing-service" provider="ledger-api" />);
    const panel = await screen.findByTestId('ppd-verification');
    await waitFor(() => expect(panel).toHaveTextContent('Not verified yet'));
    expect(panel).toHaveTextContent('apiome pact verify --provider "Ledger API"');
  });
});

describe('InteractionList', () => {
  it('shows an interaction type Apiome does not draw as its JSON, with the reason', () => {
    const pact = parsePact({
      interactions: [
        { type: 'Synchronous/Plugin', description: 'a gRPC call', plugin: 'grpc' },
        {
          type: 'Synchronous/Messages',
          description: 'a sync message',
          request: { contents: 'ping' },
          response: [{ contents: 'pong' }],
        },
      ],
    });
    render(<InteractionList interactions={pact.interactions} statuses={new Map()} />);
    const list = screen.getByTestId('ppd-interaction-list');
    expect(list).toHaveTextContent('Not drawn');
    expect(list).toHaveTextContent('Synchronous/Plugin — Apiome does not draw this type');
    expect(screen.getByLabelText('The interaction as published')).toHaveTextContent(
      '"plugin": "grpc"',
    );
    expect(list).toHaveTextContent('Request with 1 response');
    expect(screen.getByLabelText('Response contents')).toHaveTextContent('pong');
  });
});
