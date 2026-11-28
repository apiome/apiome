/**
 * The **Pacticipants** list and a pacticipant's page — PFX-5.1 (#6945).
 *
 * * **List**: rows by handle with main branch, labels and repository; each name links to the
 *   pacticipant; the label filter re-reads the list; **Load more** appends the next page; an empty
 *   workspace shows the publish command; a failed read offers a retry; axe passes.
 * * **Detail**: overview facts, branches (main marked), what each environment runs, versions with
 *   branches and tags; a branch or a tag narrows the versions and **Clear** widens them; each
 *   section fails and retries on its own; an unknown pacticipant says so; a non-http(s) build URL
 *   is never a link; axe passes.
 *
 * * **Owner** (PFX-6.4, #6956): the owner team and what it receives, **Assign owner** posts the
 *   pacticipant kind, a failed owner read fails only its own section; an id address resolves to the
 *   handle's.
 *
 * `A11Y_FIXTURE_DUMP=1` writes the docs-screenshot fixtures `pact-pacticipants` and
 * `pact-pacticipant-detail`.
 */

import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { axe } from 'jest-axe';
import 'jest-axe/extend-expect';

const mockReplace = jest.fn();
jest.mock('next/navigation', () => ({
  useRouter: () => ({ replace: mockReplace, push: jest.fn() }),
}));

jest.mock('next/link', () => ({
  __esModule: true,
  default: ({ children, href, ...props }: { children: React.ReactNode; href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

import fixture from './fixtures/pact-pacticipants.json';
import pactFixture from './fixtures/pact-detail.json';
import PacticipantsListClient from '../src/app/components/ade/pactPacticipants/PacticipantsListClient';
import PacticipantDetailClient from '../src/app/components/ade/pactPacticipants/PacticipantDetailClient';
import PacticipantRouteClient from '../src/app/components/ade/pactPacticipants/PacticipantRouteClient';
import { EnvironmentsTable, VersionsTable } from '../src/app/components/ade/pactPacticipants/PacticipantPanels';
import type {
  Pacticipant,
  PacticipantBranch,
  PacticipantEnvironment,
  PacticipantVersion,
} from '../lib/pact-pacticipants';
import { writeA11yFixture } from './helpers/a11y-fixture-dump';

const AXE_OPTIONS = { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } };
const PACTICIPANTS = fixture.pacticipants as Pacticipant[];
const BRANCHES = fixture.branches as PacticipantBranch[];
const VERSIONS = fixture.versions as PacticipantVersion[];
const ENVIRONMENTS = fixture.environments as PacticipantEnvironment[];
const BILLING = PACTICIPANTS[0];

type Route = (url: string) => { status: number; body: unknown };

let routes: Record<string, Route>;
let calls: string[];
let posts: { url: string; body: unknown }[];

/** Install a fetch that answers by exact URL. */
function installFetch() {
  calls = [];
  posts = [];
  global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push(url);
    if (init?.method === 'POST') posts.push({ url, body: JSON.parse(String(init.body ?? '{}')) });
    const route = routes[url];
    const { status, body } = route ? route(url) : { status: 404, body: { success: false, error: 'not found' } };
    return { ok: status < 400, status, json: async () => body } as Response;
  }) as unknown as typeof fetch;
}

const ok = (body: unknown): Route => () => ({ status: 200, body });

// --- the list ---------------------------------------------------------------------------------

describe('PacticipantsListClient', () => {
  beforeEach(() => {
    routes = {
      // PFX-8.10 (#7307): an editor sees New pacticipant in the header.
      '/api/access/permissions/me': ok({ success: true, data: { is_admin: false, permissions: ['pacts:view', 'pacts:create'] } }),
      '/api/pact/pacticipants': ok({ pacticipants: PACTICIPANTS, count: 3, has_more: false, next_cursor: null }),
      '/api/pact/labels': ok({ labels: fixture.labels.map((name) => ({ name })), count: 3, has_more: false }),
      '/api/pact/pacticipants?label=tier-1': ok({
        pacticipants: PACTICIPANTS.slice(0, 2),
        count: 2,
        has_more: false,
      }),
    };
    installFetch();
  });

  it('lists the pacticipants with their facts, each linking to its page, and passes axe', async () => {
    const { container } = render(<PacticipantsListClient />);
    const table = await screen.findByTestId('ppx-pacticipants-table');
    const billing = within(table).getByTestId('ppx-row-billing-service');
    expect(within(billing).getByRole('link', { name: 'Billing Service' })).toHaveAttribute(
      'href',
      '/ade/dashboard/pacts/pacticipants/billing-service',
    );
    expect(billing).toHaveTextContent('team-billing');
    expect(billing).toHaveTextContent('2026-11-24 16:40 UTC');
    expect(within(billing).getByRole('link', { name: 'https://github.com/acme/billing-service' })).toHaveAttribute(
      'rel',
      'noreferrer noopener',
    );
    expect(screen.getByTestId('ppx-row-mobile-app')).toHaveTextContent('develop');
    expect(screen.getByTestId('ppx-count')).toHaveTextContent('3 pacticipants');
    expect(await screen.findByTestId('ppx-new-open')).toHaveTextContent('New pacticipant');
    // PFX-8.1 (#7298): the Contracts tab row opens the area's other pages (it replaced the header's
    // Matrix, Can I deploy?, Webhooks and Environments buttons).
    const tabs = within(screen.getByTestId('contracts-tabs'));
    expect(tabs.getByRole('link', { name: /Pacticipants/ })).toHaveAttribute('aria-current', 'page');
    expect(tabs.getByRole('link', { name: /Matrix/ })).toHaveAttribute('href', '/ade/dashboard/pacts/matrix');
    expect(tabs.getByRole('link', { name: /Can I deploy/ })).toHaveAttribute('href', '/ade/dashboard/pacts/can-i-deploy');
    expect(tabs.getByRole('link', { name: /Webhooks/ })).toHaveAttribute('href', '/ade/dashboard/pacts/webhooks');
    expect(tabs.getByRole('link', { name: /Environments/ })).toHaveAttribute('href', '/ade/dashboard/pacts/environments');
    await screen.findByRole('option', { name: 'tier-1' });
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
    writeA11yFixture('pact-pacticipants', container.innerHTML);
  });

  it('narrows the list to a label', async () => {
    render(<PacticipantsListClient />);
    await screen.findByRole('option', { name: 'tier-1' });
    fireEvent.change(screen.getByTestId('ppx-label-filter'), { target: { value: 'tier-1' } });
    await waitFor(() => expect(screen.getByTestId('ppx-count')).toHaveTextContent('2 pacticipants with the label tier-1'));
    expect(screen.queryByTestId('ppx-row-mobile-app')).not.toBeInTheDocument();
    expect(calls).toContain('/api/pact/pacticipants?label=tier-1');
  });

  it('appends the next page on Load more', async () => {
    routes['/api/pact/pacticipants'] = ok({
      pacticipants: PACTICIPANTS.slice(0, 2),
      count: 2,
      has_more: true,
      next_cursor: 'c2',
    });
    routes['/api/pact/pacticipants?cursor=c2'] = ok({ pacticipants: PACTICIPANTS.slice(2), count: 1, has_more: false });
    render(<PacticipantsListClient />);
    expect(await screen.findByTestId('ppx-count')).toHaveTextContent('2+ pacticipants');
    fireEvent.click(screen.getByRole('button', { name: 'Load more' }));
    expect(await screen.findByTestId('ppx-row-mobile-app')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument();
  });

  it('shows the publish command in an empty workspace, without a label filter', async () => {
    routes['/api/pact/pacticipants'] = ok({ pacticipants: [], count: 0, has_more: false });
    routes['/api/pact/labels'] = ok({ labels: [], count: 0, has_more: false });
    render(<PacticipantsListClient />);
    expect(await screen.findByText('No pacticipants yet')).toBeInTheDocument();
    expect(screen.getByLabelText('Publish pacts')).toHaveTextContent('apiome pact publish ./pacts');
    expect(screen.queryByTestId('ppx-label-filter')).not.toBeInTheDocument();
  });

  it('offers a retry when the list cannot be read', async () => {
    routes['/api/pact/pacticipants'] = () => ({ status: 403, body: { success: false, error: 'Permission denied' } });
    render(<PacticipantsListClient />);
    expect(await screen.findByText('Permission denied')).toBeInTheDocument();
    routes['/api/pact/pacticipants'] = ok({ pacticipants: PACTICIPANTS, count: 3, has_more: false });
    fireEvent.click(screen.getByRole('button', { name: /try again/i }));
    expect(await screen.findByTestId('ppx-pacticipants-table')).toBeInTheDocument();
  });
});

// --- one pacticipant --------------------------------------------------------------------------

describe('PacticipantDetailClient', () => {
  const base = '/api/pact/pacticipants/billing-service';
  const ownerUrl = `/api/owners/pacticipant/${BILLING.id}`;
  const OWNED = {
    kind: 'pacticipant',
    entity_id: BILLING.id,
    owner: { team: { id: 't-1', slug: 'billing-team', name: 'Billing team' }, status: 'confirmed', source: 'manual' },
    suggestions: [],
  };

  beforeEach(() => {
    routes = {
      [base]: ok(BILLING),
      [ownerUrl]: ok(OWNED),
      '/api/teams': ok({
        teams: [
          { id: 't-1', slug: 'billing-team', name: 'Billing team' },
          { id: 't-2', slug: 'payments', name: 'Payments' },
        ],
      }),
      '/api/owners/assign': ok({ count: 1 }),
      [`${base}/branches`]: ok({ branches: BRANCHES, count: 2, has_more: false }),
      [`${base}/environments`]: ok({ environments: ENVIRONMENTS }),
      [`${base}/versions`]: ok({ versions: VERSIONS, count: 3, has_more: false }),
      [`${base}/pacts`]: ok(pactFixture.pacticipantPacts),
      [`${base}/versions?branch=main`]: ok({ versions: VERSIONS.slice(1), count: 2, has_more: false }),
      [`${base}/versions?tag=prod`]: ok({ versions: VERSIONS.slice(1, 2), count: 1, has_more: false }),
    };
    installFetch();
  });

  it('shows the overview, branches, environments and versions, and passes axe', async () => {
    const { container } = render(<PacticipantDetailClient slug="billing-service" />);
    // PFX-8.18 (#7315): the Export page opens on a Postman collection of this pacticipant's pacts.
    expect(screen.getByTestId('ppx-export')).toHaveAttribute('href', '/ade/dashboard/pacts/export?kind=postman&provider=billing-service');
    const facts = await screen.findByTestId('ppx-facts');
    expect(facts).toHaveTextContent('Handlebilling-service');
    expect(facts).toHaveTextContent('Bound toConsumer');
    const branches = await screen.findByTestId('ppx-branches-table');
    expect(within(branches).getByText('Main')).toBeInTheDocument();
    expect(branches).toHaveTextContent('3f2a9c1b7e6d');
    const production = await screen.findByTestId('ppx-env-production');
    // PFX-5.7 (#6951): each environment opens its own page.
    expect(within(production).getByRole('link')).toHaveAttribute('href', '/ade/dashboard/pacts/environments/production');
    expect(production).toHaveTextContent('Production');
    expect(production).toHaveTextContent('3f2a9c1b7e6d · 2026-11-22 17:00 UTC');
    expect(screen.getByTestId('ppx-env-staging')).toHaveTextContent('2.4.0 · us-east');
    expect(screen.getByTestId('ppx-env-staging')).toHaveTextContent('2.4.0 · 2026-11-12 10:00 UTC');
    expect(production).toHaveTextContent('No release');
    const versions = await screen.findByTestId('ppx-versions-table');
    expect(within(versions).getAllByRole('row')).toHaveLength(4);
    expect(screen.getByTestId('ppx-versions-summary')).toHaveTextContent('3 versions');
    const pacts = await screen.findByTestId('ppx-pacts-table');
    expect(within(pacts).getByRole('link', { name: 'Billing Service → Ledger API' })).toHaveAttribute(
      'href',
      '/ade/dashboard/pacts/pacticipants/billing-service/pacts/ledger-api',
    );
    expect(screen.getByTestId('ppx-pacts-count')).toHaveTextContent('3');
    expect(within(pacts).getAllByText('Provider')).toHaveLength(1);
    expect(screen.getByTestId('ppx-network-link')).toHaveAttribute(
      'href',
      '/ade/dashboard/pacts/pacticipants/billing-service/network',
    );
    // A provider of at least one pact (PFX-5.5): its Verification page.
    expect(screen.getByTestId('ppx-verification-link')).toHaveAttribute(
      'href',
      '/ade/dashboard/pacts/pacticipants/billing-service/verification',
    );
    // PFX-6.4 (#6956): the owner team and what it receives.
    expect(await screen.findByTestId('entity-owner-cell')).toHaveTextContent('Billing team');
    expect(screen.getByTestId('entity-owner-description')).toHaveTextContent('failed verifications go to this team');
    await waitFor(() => expect(within(screen.getByTestId('entity-owner-select')).getByText('Payments')).toBeInTheDocument());
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
    writeA11yFixture('pact-pacticipant-detail', container.innerHTML);
  });

  it('narrows the versions to a branch or a tag, and Clear widens them again', async () => {
    render(<PacticipantDetailClient slug="billing-service" />);
    const branches = await screen.findByTestId('ppx-branches-table');
    fireEvent.click(within(branches).getByRole('button', { name: 'Show the versions on main' }));
    await waitFor(() => expect(screen.getByTestId('ppx-versions-summary')).toHaveTextContent('2 versions on branch main'));
    expect(screen.getByRole('group', { name: 'Version filter' })).toHaveTextContent('Branch: main');

    fireEvent.click(screen.getByRole('button', { name: 'Clear' }));
    await waitFor(() => expect(screen.getByTestId('ppx-versions-summary')).toHaveTextContent(/^3 versions$/));

    fireEvent.click(await screen.findByRole('button', { name: 'Show the versions tagged prod' }));
    await waitFor(() => expect(screen.getByTestId('ppx-versions-summary')).toHaveTextContent('1 version tagged prod'));
    expect(calls).toContain(`${base}/versions?tag=prod`);
  });

  it('keeps the other sections when one cannot be read, and retries it', async () => {
    routes[`${base}/environments`] = () => ({ status: 403, body: { success: false, error: 'Permission denied' } });
    render(<PacticipantDetailClient slug="billing-service" />);
    expect(await screen.findByText('The environments could not be read')).toBeInTheDocument();
    expect(await screen.findByTestId('ppx-versions-table')).toBeInTheDocument();
    routes[`${base}/environments`] = ok({ environments: [] });
    fireEvent.click(within(screen.getByTestId('ppx-environments')).getByRole('button', { name: /try again/i }));
    expect(await screen.findByTestId('ppx-environments-empty')).toHaveTextContent('apiome pact record-deployment');
  });

  it('shows the publish command when no pact names the pacticipant, and retries a failed read', async () => {
    routes[`${base}/pacts`] = () => ({ status: 400, body: { success: false, error: 'Pacticipant x not found' } });
    render(<PacticipantDetailClient slug="billing-service" />);
    expect(await screen.findByText('The pacts could not be read')).toBeInTheDocument();
    routes[`${base}/pacts`] = ok({ matrix: [] });
    fireEvent.click(within(screen.getByTestId('ppx-pacts')).getByRole('button', { name: /try again/i }));
    expect(await screen.findByTestId('ppx-pacts-empty')).toHaveTextContent('apiome pact publish');
    // No integration, so no network to draw.
    expect(screen.queryByTestId('ppx-network-link')).not.toBeInTheDocument();
    expect(screen.queryByTestId('ppx-verification-link')).not.toBeInTheDocument();
  });

  it('says when the pacticipant does not exist, with the way back', async () => {
    routes[base] = () => ({ status: 404, body: { success: false, error: 'No pacticipant billing-service' } });
    render(<PacticipantDetailClient slug="billing-service" />);
    expect(await screen.findByText('No pacticipant billing-service')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'All pacticipants' })).toHaveAttribute(
      'href',
      '/ade/dashboard/pacts/pacticipants',
    );
  });

  it('assigns an owner team to the pacticipant and reads the owner again', async () => {
    render(<PacticipantDetailClient slug="billing-service" />);
    const select = await screen.findByTestId('entity-owner-select');
    await waitFor(() => expect(within(select).getByText('Payments')).toBeInTheDocument());
    const ownerReads = calls.filter((url) => url === ownerUrl).length;
    fireEvent.change(select, { target: { value: 'payments' } });
    fireEvent.click(screen.getByTestId('entity-owner-assign'));
    await waitFor(() =>
      expect(posts).toContainEqual({
        url: '/api/owners/assign',
        body: { team: 'payments', entities: [{ kind: 'pacticipant', id: BILLING.id }] },
      }),
    );
    await waitFor(() => expect(calls.filter((url) => url === ownerUrl).length).toBeGreaterThan(ownerReads));
  });

  it('shows a pacticipant with no owner as unowned, still offering Assign owner', async () => {
    routes[ownerUrl] = ok({ kind: 'pacticipant', entity_id: BILLING.id, owner: null, suggestions: [] });
    render(<PacticipantDetailClient slug="billing-service" />);
    expect(await screen.findByTestId('entity-owner-assign')).toHaveTextContent('Assign owner');
  });

  it('keeps the page when the owner cannot be read, and retries it', async () => {
    routes[ownerUrl] = () => ({ status: 403, body: { success: false, error: 'Permission denied' } });
    render(<PacticipantDetailClient slug="billing-service" />);
    const failed = await screen.findByTestId('ppx-owner-error');
    expect(failed).toHaveTextContent('Permission denied');
    expect(await screen.findByTestId('ppx-versions-table')).toBeInTheDocument();
    routes[ownerUrl] = ok(OWNED);
    fireEvent.click(within(failed).getByRole('button', { name: /try again/i }));
    expect(await screen.findByTestId('entity-owner-cell')).toHaveTextContent('Billing team');
  });

  it('pages the versions with Load more', async () => {
    routes[`${base}/versions`] = ok({ versions: VERSIONS.slice(0, 2), count: 2, has_more: true, next_cursor: 'v2' });
    routes[`${base}/versions?cursor=v2`] = ok({ versions: VERSIONS.slice(2), count: 1, has_more: false });
    render(<PacticipantDetailClient slug="billing-service" />);
    expect(await screen.findByTestId('ppx-versions-summary')).toHaveTextContent('2+ versions');
    fireEvent.click(screen.getByRole('button', { name: 'Load more' }));
    await waitFor(() => expect(screen.getByTestId('ppx-versions-summary')).toHaveTextContent(/^3 versions$/));
  });
});

// --- an id address (PFX-6.4) ------------------------------------------------------------------

describe('PacticipantRouteClient', () => {
  beforeEach(() => {
    mockReplace.mockClear();
    routes = {};
    installFetch();
  });

  it('replaces an id address with the handle it names', async () => {
    routes[`/api/pact/pacticipants/${BILLING.id}`] = ok(BILLING);
    render(<PacticipantRouteClient reference={BILLING.id} />);
    await waitFor(() => expect(mockReplace).toHaveBeenCalledWith('/ade/dashboard/pacts/pacticipants/billing-service'));
    expect(screen.getByText('Opening the pacticipant…')).toBeInTheDocument();
  });

  it('renders a handle address without resolving it', async () => {
    routes['/api/pact/pacticipants/billing-service'] = ok(BILLING);
    render(<PacticipantRouteClient reference="billing-service" />);
    expect(await screen.findByTestId('ppx-facts')).toBeInTheDocument();
    expect(mockReplace).not.toHaveBeenCalled();
  });

  it('renders the page (and its error) when an id names nothing', async () => {
    const missing = '00000000-0000-4000-8000-000000000000';
    routes[`/api/pact/pacticipants/${missing}`] = () => ({ status: 404, body: { success: false, error: 'No such pacticipant' } });
    render(<PacticipantRouteClient reference={missing} />);
    expect(await screen.findByText('No such pacticipant')).toBeInTheDocument();
    expect(mockReplace).not.toHaveBeenCalled();
  });
});

// --- the panels -------------------------------------------------------------------------------

describe('panels', () => {
  it('never links a build URL that is not http(s)', () => {
    render(
      <VersionsTable
        versions={[{ ...VERSIONS[0], build_url: 'javascript:alert(1)' }]}
        onPickBranch={() => undefined}
        onPickTag={() => undefined}
      />,
    );
    expect(screen.queryByRole('link', { name: 'Build' })).not.toBeInTheDocument();
  });

  it('reports an environment that could not be read instead of hiding it', () => {
    render(
      <EnvironmentsTable
        environments={[{ ...ENVIRONMENTS[0], deployed: [], error: 'Releases: Database busy' }]}
        pacticipantName="Billing Service"
      />,
    );
    expect(screen.getByTestId('ppx-env-production')).toHaveTextContent('Could not be read. Releases: Database busy');
  });
});
