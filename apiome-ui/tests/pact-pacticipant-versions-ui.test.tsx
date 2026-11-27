/**
 * Version management and badges — PFX-8.11 (#7308).
 *
 * * **Versions tab**: the versions with where each runs; axe passes; search narrows the loaded
 *   versions and says when more pages exist; inline **+ tag** puts the tag and shows it, and a
 *   refused tag is said under the field; **Delete version** of a deployed version is blocked with
 *   "Record its undeployment first" and offers no delete; another version is deleted with its
 *   reason and leaves the list; the bulk bar tags several versions and names the one REST refused,
 *   and deletes the deletable ones while naming the deployed one; **Deleted** lists what can be
 *   restored and **Restore** posts; **Deployed** reads what each environment runs; **Unverified**
 *   reads the matrix; a read-only role sees no tag, delete, restore or select box; an empty list
 *   and a failed read each say so.
 * * **Badges** (Settings): the preview is the SVG REST serves and the Markdown names its URL; a
 *   private project says it serves no badge; no linked project says how to get one.
 *
 * `A11Y_FIXTURE_DUMP=1` writes the docs-screenshot fixture `pact-pacticipant-versions`.
 */

import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { axe } from 'jest-axe';
import 'jest-axe/extend-expect';

jest.mock('next/navigation', () => ({
  useRouter: () => ({ replace: jest.fn(), push: jest.fn() }),
}));

jest.mock('next/link', () => ({
  __esModule: true,
  default: ({ children, href, ...props }: { children: React.ReactNode; href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

import PacticipantVersionsClient from '../src/app/components/ade/pactPacticipants/PacticipantVersionsClient';
import PacticipantBadgesPanel from '../src/app/components/ade/pactPacticipants/PacticipantBadgesPanel';
import type { Pacticipant, PacticipantEnvironment, PacticipantVersion } from '../lib/pact-pacticipants';
import { liveMarkup, writeA11yFixture } from './helpers/a11y-fixture-dump';

const AXE_OPTIONS = { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } };

const ORDERS: Pacticipant = {
  id: '22222222-2222-4222-8222-222222222222',
  slug: 'orders-ui',
  name: 'Orders UI',
  main_branch: 'main',
  repository_url: 'https://github.com/acme/orders-ui',
  project_id: 'p-orders',
  labels: ['web'],
  created_at: '2026-03-14T09:00:00Z',
};

const version = (number: string, seq: number, extra: Partial<PacticipantVersion> = {}): PacticipantVersion => ({
  id: `v-${seq}`,
  pacticipant_id: ORDERS.id,
  number,
  seq,
  branches: ['main'],
  tags: [],
  created_at: '2026-11-20T10:00:00Z',
  ...extra,
});

const VERSIONS: PacticipantVersion[] = [
  version('3.4.0+a1c9e02', 4, { branches: ['feature/credit-notes'], tags: ['dev'], created_at: '2026-11-27T10:00:00Z' }),
  version('3.3.2+77c0aa1', 3, { tags: ['prod'], created_at: '2026-11-21T10:00:00Z' }),
  version('3.3.1+1d09ffe', 2, { created_at: '2026-11-06T10:00:00Z' }),
];

const DELETED = [
  {
    ...version('3.2.9+c4410b7', 1, { branches: ['spike/new-cart'], created_at: '2026-09-27T10:00:00Z' }),
    deleted_at: '2026-11-25T08:00:00Z',
    deleted_by_label: 'ada',
    delete_reason: 'abandoned spike',
    delete_cause: 'version',
    purge_after: '2026-12-25T08:00:00Z',
  },
];

const ENVIRONMENTS: PacticipantEnvironment[] = [
  {
    uuid: 'e-prod',
    name: 'production',
    displayName: 'Production',
    production: true,
    deployed: [{ version: '3.3.2+77c0aa1', applicationInstance: null, deployedAt: '2026-11-22T17:00:00Z' }],
    released: [],
  },
  {
    uuid: 'e-staging',
    name: 'staging',
    displayName: 'Staging',
    production: false,
    deployed: [{ version: '3.3.2+77c0aa1', applicationInstance: null, deployedAt: '2026-11-22T15:00:00Z' }],
    released: [],
  },
];

const EDITOR = { is_admin: false, permissions: ['pacts:view', 'pacts:create', 'pacts:edit', 'pacts:delete'] };
const VIEWER = { is_admin: false, permissions: ['pacts:view'] };
const base = '/api/pact/pacticipants/orders-ui';
const enc = encodeURIComponent;

type Call = { url: string; method: string };
type Answer = (call: Call) => { status: number; body: unknown };
let routes: Record<string, Answer>;
let calls: Call[];

/** Answer by `METHOD url` first, then by url. */
function installFetch() {
  calls = [];
  global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? 'GET';
    calls.push({ url, method });
    const route = routes[`${method} ${url}`] ?? routes[url];
    const { status, body } = route ? route({ url, method }) : { status: 404, body: { success: false, error: 'not found' } };
    return { ok: status < 400, status, json: async () => body } as Response;
  }) as unknown as typeof fetch;
}

const ok =
  (body: unknown): Answer =>
  () => ({ status: 200, body });
const page = (versions: unknown[], hasMore = false) =>
  ok({ versions, count: versions.length, has_more: hasMore, next_cursor: hasMore ? 'c2' : null });
const writes = () => calls.filter((call) => call.method !== 'GET');

function baseRoutes(permissions = EDITOR): Record<string, Answer> {
  return {
    '/api/access/permissions/me': ok({ success: true, data: permissions }),
    [base]: ok(ORDERS),
    [`${base}/environments`]: ok({ environments: ENVIRONMENTS }),
    [`${base}/versions`]: page(VERSIONS),
    [`${base}/versions?state=deleted`]: page(DELETED),
  };
}

/** Radix `DropdownMenu.Trigger` opens on `pointerdown`, which jsdom does not synthesise. */
function openMenu(trigger: HTMLElement) {
  fireEvent.keyDown(trigger, { key: 'Enter' });
}

async function renderTab() {
  const view = render(<PacticipantVersionsClient slug="orders-ui" />);
  await screen.findByTestId('ppx-versions-manage-table');
  // The Running in column is filled once the environments are read.
  await within(screen.getByTestId('ppx-version-row-3.3.2+77c0aa1')).findByText('Production');
  return view;
}

beforeEach(() => {
  routes = baseRoutes();
  installFetch();
  Object.assign(navigator, { clipboard: { writeText: jest.fn(async () => undefined) } });
});

describe('the Versions tab', () => {
  it('lists the versions with where each runs, and passes axe', async () => {
    const { container } = await renderTab();
    expect(screen.getByTestId('ppx-tab-versions')).toHaveAttribute('aria-current', 'page');
    const deployed = within(screen.getByTestId('ppx-version-row-3.3.2+77c0aa1'));
    expect(deployed.getByText('Staging')).toBeInTheDocument();
    expect(deployed.getByText('prod')).toBeInTheDocument();
    expect(screen.getByTestId('ppx-versions-view-main')).toHaveTextContent('main');
    expect(screen.getByTestId('ppx-versions-view-deleted')).toHaveTextContent('Deleted1');
    expect(screen.getByTestId('ppx-versions-count')).toHaveTextContent('3 of 3 versions');
    // Select two rows for the screenshot: the bulk bar and its command block show.
    fireEvent.click(screen.getByRole('checkbox', { name: 'Select 3.4.0+a1c9e02' }));
    fireEvent.click(screen.getByRole('checkbox', { name: 'Select 3.3.1+1d09ffe' }));
    expect(screen.getByTestId('ppx-versions-bulk')).toHaveTextContent('2 selected');
    expect(screen.getByTestId('ppx-versions-command')).toHaveTextContent('apiome pact create-version-tag');
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
    writeA11yFixture('pact-pacticipant-versions', liveMarkup(container));
  });

  it('searches the loaded versions and says when more pages exist', async () => {
    routes[`${base}/versions`] = page(VERSIONS, true);
    await renderTab();
    fireEvent.change(screen.getByTestId('ppx-versions-search'), { target: { value: 'credit' } });
    expect(screen.getByTestId('ppx-version-row-3.4.0+a1c9e02')).toBeInTheDocument();
    expect(screen.queryByTestId('ppx-version-row-3.3.1+1d09ffe')).not.toBeInTheDocument();
    expect(screen.getByTestId('ppx-versions-search-note')).toHaveTextContent(
      'Searching the 3 versions loaded so far. Load more to search further.',
    );
    fireEvent.change(screen.getByTestId('ppx-versions-search'), { target: { value: 'nothing-like-it' } });
    expect(screen.getByTestId('ppx-versions-empty')).toHaveTextContent('No loaded version matches the search.');
  });

  it('tags a version inline, and says why a tag is refused', async () => {
    routes[`PUT ${base}/versions/${enc('3.3.1+1d09ffe')}/tags/feat/x`] = ok({ ...VERSIONS[2], tags: ['feat/x'] });
    routes[`PUT ${base}/versions/${enc('3.3.1+1d09ffe')}/tags/bad`] = () => ({
      status: 403,
      body: { success: false, error: 'Permission denied: pacts:create' },
    });
    await renderTab();
    fireEvent.click(screen.getByTestId('ppx-add-tag-3.3.1+1d09ffe'));
    const input = screen.getByTestId('ppx-tag-input-3.3.1+1d09ffe');
    fireEvent.change(input, { target: { value: 'x'.repeat(256) } });
    fireEvent.submit(input.closest('form')!);
    expect(await screen.findByRole('alert')).toHaveTextContent('A tag is at most 255 characters.');
    expect(writes()).toEqual([]);
    fireEvent.change(input, { target: { value: 'bad' } });
    fireEvent.submit(input.closest('form')!);
    expect(await screen.findByText('Permission denied: pacts:create')).toBeInTheDocument();
    fireEvent.change(screen.getByTestId('ppx-tag-input-3.3.1+1d09ffe'), { target: { value: 'feat/x' } });
    fireEvent.submit(screen.getByTestId('ppx-tag-input-3.3.1+1d09ffe').closest('form')!);
    expect(await within(screen.getByTestId('ppx-version-row-3.3.1+1d09ffe')).findByText('feat/x')).toBeInTheDocument();
    expect(screen.getByTestId('ppx-versions-outcome')).toHaveTextContent('Tagged 3.3.1+1d09ffe with feat/x.');
  });

  it('blocks deleting a deployed version: record its undeployment first', async () => {
    await renderTab();
    openMenu(screen.getByTestId('ppx-version-menu-3.3.2+77c0aa1'));
    fireEvent.click(await screen.findByTestId('ppx-delete-version-3.3.2+77c0aa1'));
    const dialog = await screen.findByTestId('ppx-delete-versions-dialog');
    expect(within(dialog).getByTestId('ppx-delete-versions-blocked')).toHaveTextContent(
      '3.3.2+77c0aa1 is running in Production and Staging. Record its undeployment first.',
    );
    expect(within(dialog).queryByTestId('ppx-delete-versions-confirm')).not.toBeInTheDocument();
    expect(writes()).toEqual([]);
  });

  it('deletes a version with its reason and takes it out of the list', async () => {
    routes[`DELETE ${base}/versions/${enc('3.3.1+1d09ffe')}?reason=bad%20build`] = ok({});
    await renderTab();
    openMenu(screen.getByTestId('ppx-version-menu-3.3.1+1d09ffe'));
    fireEvent.click(await screen.findByTestId('ppx-delete-version-3.3.1+1d09ffe'));
    const dialog = await screen.findByTestId('ppx-delete-versions-dialog');
    expect(dialog).toHaveTextContent('You can restore it from Deleted until it is purged.');
    expect(within(dialog).getByTestId('ppx-delete-versions-command')).toHaveTextContent('apiome pact delete-version');
    fireEvent.change(within(dialog).getByTestId('ppx-delete-versions-reason'), { target: { value: 'bad build' } });
    fireEvent.click(within(dialog).getByTestId('ppx-delete-versions-confirm'));
    await waitFor(() => expect(screen.queryByTestId('ppx-version-row-3.3.1+1d09ffe')).not.toBeInTheDocument());
    expect(writes().map((c) => `${c.method} ${c.url}`)).toEqual([
      `DELETE ${base}/versions/${enc('3.3.1+1d09ffe')}?reason=bad%20build`,
    ]);
    expect(screen.getByTestId('ppx-versions-outcome')).toHaveTextContent('Deleted 1 version.');
  });

  it('bulk-tags the selection and names the version REST refused', async () => {
    routes[`PUT ${base}/versions/${enc('3.4.0+a1c9e02')}/tags/qa`] = ok({ ...VERSIONS[0], tags: ['dev', 'qa'] });
    routes[`PUT ${base}/versions/${enc('3.3.1+1d09ffe')}/tags/qa`] = () => ({
      status: 404,
      body: { success: false, error: 'no version 3.3.1+1d09ffe' },
    });
    await renderTab();
    fireEvent.click(screen.getByRole('checkbox', { name: 'Select 3.4.0+a1c9e02' }));
    fireEvent.click(screen.getByRole('checkbox', { name: 'Select 3.3.1+1d09ffe' }));
    fireEvent.change(screen.getByTestId('ppx-bulk-tag-input'), { target: { value: 'qa' } });
    fireEvent.submit(screen.getByTestId('ppx-bulk-tag-input').closest('form')!);
    expect(await screen.findByTestId('ppx-versions-outcome')).toHaveTextContent(
      'Tagged 1 version with qa. Not changed — 3.3.1+1d09ffe: no version 3.3.1+1d09ffe',
    );
    expect(within(screen.getByTestId('ppx-version-row-3.4.0+a1c9e02')).getByText('qa')).toBeInTheDocument();
  });

  it('bulk-deletes the deletable versions and names the deployed one', async () => {
    routes[`DELETE ${base}/versions/${enc('3.3.1+1d09ffe')}`] = ok({});
    await renderTab();
    fireEvent.click(screen.getByRole('checkbox', { name: 'Select 3.3.2+77c0aa1' }));
    fireEvent.click(screen.getByRole('checkbox', { name: 'Select 3.3.1+1d09ffe' }));
    fireEvent.click(screen.getByTestId('ppx-bulk-delete'));
    const dialog = await screen.findByTestId('ppx-delete-versions-dialog');
    expect(within(dialog).getByTestId('ppx-delete-versions-blocked')).toHaveTextContent('Record its undeployment first.');
    fireEvent.click(within(dialog).getByTestId('ppx-delete-versions-confirm'));
    expect(await screen.findByTestId('ppx-versions-outcome')).toHaveTextContent(
      'Deleted 1 version. They can be restored from Deleted until they are purged. Not changed — 3.3.2+77c0aa1: 3.3.2+77c0aa1 is running in Production and Staging. Record its undeployment first.',
    );
    expect(writes().map((c) => c.method + ' ' + c.url)).toEqual([`DELETE ${base}/versions/${enc('3.3.1+1d09ffe')}`]);
  });

  it('lists the deleted versions and restores one', async () => {
    routes[`POST ${base}/versions/${enc('3.2.9+c4410b7')}/restore`] = ok(DELETED[0]);
    await renderTab();
    fireEvent.click(screen.getByTestId('ppx-versions-view-deleted'));
    const row = await screen.findByTestId('ppx-version-row-3.2.9+c4410b7');
    expect(row).toHaveTextContent('by ada — abandoned spike');
    fireEvent.click(within(row).getByTestId('ppx-restore-3.2.9+c4410b7'));
    expect(await screen.findByTestId('ppx-versions-outcome')).toHaveTextContent(
      'Restored 3.2.9+c4410b7 with its pacts, results and deployments.',
    );
    expect(screen.getByTestId('ppx-versions-empty')).toHaveTextContent('No deleted version can be restored.');
  });

  it('reads the Deployed view from the environments and the Unverified view from the matrix', async () => {
    routes[`${base}/versions/${enc('3.3.2+77c0aa1')}`] = ok(VERSIONS[1]);
    routes[`${base}/versions/${enc('3.4.0+a1c9e02')}`] = ok(VERSIONS[0]);
    const matrixUrl = '/api/pact/matrix?q%5B0%5D%5Bpacticipant%5D=orders-ui&limit=1000';
    routes[matrixUrl] = ok({
      summary: { deployable: null, reason: '', success: 0, failed: 0, unknown: 1 },
      matrix: [
        {
          consumer: { name: 'Orders UI', version: { number: '3.4.0+a1c9e02' }, _links: { self: { href: '/pacticipants/orders-ui' } } },
          provider: { name: 'Billing', version: null, _links: { self: { href: '/pacticipants/billing' } } },
          pact: { createdAt: '2026-11-27T10:00:00Z' },
          verificationResult: null,
        },
      ],
    });
    await renderTab();
    fireEvent.click(screen.getByTestId('ppx-versions-view-deployed'));
    expect(await screen.findByTestId('ppx-version-row-3.3.2+77c0aa1')).toBeInTheDocument();
    expect(screen.queryByTestId('ppx-version-row-3.4.0+a1c9e02')).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId('ppx-versions-view-unverified'));
    await waitFor(() => expect(calls.some((c) => c.url === matrixUrl)).toBe(true));
    expect(await screen.findByTestId('ppx-version-row-3.4.0+a1c9e02')).toBeInTheDocument();
    expect(screen.queryByTestId('ppx-version-row-3.3.2+77c0aa1')).not.toBeInTheDocument();
  });

  it('shows a read-only role no tag, delete, restore or select box', async () => {
    routes = baseRoutes(VIEWER);
    installFetch();
    await renderTab();
    await waitFor(() => expect(calls.some((c) => c.url === '/api/access/permissions/me')).toBe(true));
    expect(screen.queryByTestId('ppx-add-tag-3.3.1+1d09ffe')).not.toBeInTheDocument();
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
    openMenu(screen.getByTestId('ppx-version-menu-3.3.1+1d09ffe'));
    expect(await screen.findByText('Can I deploy this?')).toBeInTheDocument();
    expect(screen.queryByTestId('ppx-delete-version-3.3.1+1d09ffe')).not.toBeInTheDocument();
    fireEvent.keyDown(document.activeElement ?? document.body, { key: 'Escape' });
    fireEvent.click(screen.getByTestId('ppx-versions-view-deleted'));
    await screen.findByTestId('ppx-version-row-3.2.9+c4410b7');
    expect(screen.queryByTestId('ppx-restore-3.2.9+c4410b7')).not.toBeInTheDocument();
  });

  it('says when nothing was published, and when the versions could not be read', async () => {
    routes[`${base}/versions`] = page([]);
    render(<PacticipantVersionsClient slug="orders-ui" />);
    expect(await screen.findByTestId('ppx-versions-empty')).toHaveTextContent(
      'Nothing published under Orders UI yet. Publish a pact, or record one from a mock.',
    );
    routes[`${base}/versions`] = () => ({ status: 403, body: { success: false, error: 'Permission denied: pacts:view' } });
    fireEvent.click(screen.getByTestId('ppx-versions-view-all'));
    fireEvent.click(screen.getByTestId('ppx-versions-view-main'));
    expect(await screen.findByText('The versions could not be read')).toBeInTheDocument();
  });
});

describe('the Badges panel', () => {
  const PROJECTS = [{ id: 'p-orders', name: 'Orders Web', slug: 'orders-web' }];
  const SVG = '<svg xmlns="http://www.w3.org/2000/svg" role="img" aria-label="pact: orders-ui: failing"/>';

  beforeEach(() => {
    routes[`${base}/pacts`] = ok({
      matrix: [
        {
          consumer: { name: 'Orders UI', version: { number: '1' }, _links: { self: { href: '/pacticipants/orders-ui' } } },
          provider: { name: 'Billing Service', version: null, _links: { self: { href: '/pacticipants/billing-service' } } },
          pact: { createdAt: '2026-11-27T10:00:00Z' },
          verificationResult: null,
        },
      ],
    });
  });

  it('previews the SVG REST serves and offers the Markdown', async () => {
    routes['/api/pact/badges?project=orders-web&pacticipant=orders-ui'] = ok({ tenant: 'acme', status: 'failing', svg: SVG });
    render(<PacticipantBadgesPanel pacticipant={ORDERS} projects={PROJECTS} />);
    const image = await screen.findByTestId('ppx-badges-image');
    expect(image).toHaveAttribute('src', `data:image/svg+xml;charset=utf-8,${encodeURIComponent(SVG)}`);
    expect(image).toHaveAttribute('alt', 'Pact badge: failing');
    expect(screen.getByTestId('ppx-badges-markdown')).toHaveTextContent(
      '![pact](http://localhost:8000/v1/browse/tenants/acme/projects/orders-web/pact-badges/pacticipants/orders-ui/badge.svg)',
    );
    expect(screen.getByTestId('ppx-badges-selector-note')).toHaveTextContent('answer 501');
  });

  it('switches to one pact’s badge', async () => {
    routes['/api/pact/badges?project=orders-web&pacticipant=orders-ui'] = ok({ tenant: 'acme', status: 'failing', svg: SVG });
    routes['/api/pact/badges?project=orders-web&provider=billing-service&consumer=orders-ui'] = ok({
      tenant: 'acme',
      status: 'verified',
      svg: SVG,
    });
    render(<PacticipantBadgesPanel pacticipant={ORDERS} projects={PROJECTS} />);
    await screen.findByTestId('ppx-badges-image');
    await waitFor(() => expect(screen.getByTestId('ppx-badges-for').querySelectorAll('option')).toHaveLength(2));
    await act(async () => {
      fireEvent.change(screen.getByTestId('ppx-badges-for'), {
        target: { value: 'pair:billing-service|orders-ui' },
      });
    });
    expect(await screen.findByAltText('Pact badge: verified')).toBeInTheDocument();
    expect(screen.getByTestId('ppx-badges-markdown')).toHaveTextContent(
      '/pact-badges/pacts/provider/billing-service/consumer/orders-ui/badge.svg',
    );
  });

  it('says a private project serves no badge, and how to get one without a project', async () => {
    routes['/api/pact/badges?project=orders-web&pacticipant=orders-ui'] = () => ({
      status: 404,
      body: { success: false, error: 'No badge' },
    });
    const { unmount } = render(<PacticipantBadgesPanel pacticipant={ORDERS} projects={PROJECTS} />);
    expect(await screen.findByTestId('ppx-badges-none')).toHaveTextContent(
      'Orders Web serves no badge: it has no published, public version.',
    );
    unmount();
    render(<PacticipantBadgesPanel pacticipant={{ ...ORDERS, project_id: null }} projects={PROJECTS} />);
    expect(screen.getByTestId('ppx-badges-no-project')).toHaveTextContent('linked to a public project');
  });
});
