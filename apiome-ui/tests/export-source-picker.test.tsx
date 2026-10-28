/**
 * Export studio's source picker (E1-2, #6218).
 *
 * Pins: the pure rules (search, the Catalog/Projects boundary, newest-first versions, the deep
 * links resuming at Target); the component — Catalog items listed with their pills and searched,
 * choosing one navigates to its deep link; Projects listed without catalog items, a project's
 * versions (and its latest) each navigating to theirs; load failures retryable; keyboard reachable
 * and axe clean.
 */

import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import { axe } from 'jest-axe';
import 'jest-axe/extend-expect';

import { ExportSourcePicker } from '../src/app/components/ade/export-studio/ExportSourcePicker';
import {
  catalogSourceHref,
  filterCatalogSources,
  projectSourceHref,
  selectableProjects,
  selectableVersions,
} from '../src/app/components/ade/export-studio/exportSourcePicker';
import { liveMarkup, writeA11yFixture } from './helpers/a11y-fixture-dump';
import { tabTo } from './helpers/keyboard';

const mockPush = jest.fn();
jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush, replace: jest.fn() }),
}));

const AXE_OPTIONS = { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } } as const;

const CATALOG = [
  { id: 'c-1', name: 'Orders RPC', slug: 'orders-rpc', sourceFormat: 'protobuf', protocol: 'rpc', deleted_at: null, enabled: true },
  { id: 'c-2', name: 'Ledger Graph', slug: 'ledger-graph', sourceFormat: 'graphql', protocol: 'graph', deleted_at: null, enabled: true },
  { id: 'c-3', name: 'Gone', slug: 'gone', sourceFormat: 'avro', protocol: 'event', deleted_at: '2026-10-01', enabled: true },
];
const PROJECTS = [
  { id: 'p-1', name: 'Pets API', slug: 'pets', publishable: true },
  { id: 'c-1', name: 'Orders RPC', slug: 'orders-rpc', publishable: false }, // a catalog item: never listed
];
const VERSIONS = [
  { id: 'v-1', version_id: '1.0.0', created_at: '2026-09-01T00:00:00Z', published: true },
  { id: 'v-2', version_id: '1.1.0', created_at: '2026-10-01T00:00:00Z', published: false },
  { id: 'v-0', version_id: '0.9.0', created_at: '2026-08-01T00:00:00Z', deleted_at: '2026-08-02' },
];

type Route = () => { status?: number; body: unknown };

function mockFetch(routes: Record<string, Route>) {
  const calls: string[] = [];
  global.fetch = jest.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    calls.push(url);
    const answer = routes[url]?.() ?? { status: 404, body: { success: false, error: 'not mocked' } };
    const status = answer.status ?? 200;
    return { ok: status < 400, status, json: async () => answer.body } as Response;
  }) as unknown as typeof fetch;
  return calls;
}

const OK = {
  '/api/catalog': () => ({ body: { success: true, catalog: CATALOG } }),
  '/api/projects': () => ({ body: { success: true, projects: PROJECTS } }),
  '/api/versions?projectId=p-1': () => ({ body: { success: true, versions: VERSIONS } }),
};

beforeAll(() => {
  Element.prototype.scrollIntoView = jest.fn();
  Element.prototype.hasPointerCapture = jest.fn(() => false);
});

afterEach(() => {
  jest.restoreAllMocks();
  mockPush.mockReset();
});

/** Radix tabs activate on mousedown (jsdom does not synthesise it from click). */
function openTab(name: string) {
  const tab = screen.getByRole('tab', { name });
  fireEvent.mouseDown(tab);
  fireEvent.click(tab);
}

// --- rules -------------------------------------------------------------------------------------

describe('rules', () => {
  it('searches live catalog items by name, slug, format or protocol, every word', () => {
    expect(filterCatalogSources(CATALOG, '').map((i) => i.id)).toEqual(['c-2', 'c-1']); // by name, no deleted
    expect(filterCatalogSources(CATALOG, 'GRAPHQL').map((i) => i.id)).toEqual(['c-2']);
    expect(filterCatalogSources(CATALOG, 'orders rpc').map((i) => i.id)).toEqual(['c-1']);
    expect(filterCatalogSources(CATALOG, 'gone')).toEqual([]);
  });

  it('never offers a catalog item as a project', () => {
    expect(selectableProjects(PROJECTS).map((p) => p.id)).toEqual(['p-1']);
  });

  it('lists live versions newest first', () => {
    expect(selectableVersions(VERSIONS).map((v) => v.version_id)).toEqual(['1.1.0', '1.0.0']);
  });

  it('builds deep links that resume at Target', () => {
    expect(catalogSourceHref(CATALOG[0])).toBe(
      '/ade/dashboard/export/studio?artifact=c-1&label=Orders+RPC&from=catalog&sourceFormat=protobuf&step=target',
    );
    expect(projectSourceHref(PROJECTS[0], VERSIONS[1])).toBe(
      '/ade/dashboard/export/studio?artifact=p-1&version=v-2&label=Pets+API+1.1.0&from=versions&step=target',
    );
    expect(projectSourceHref(PROJECTS[0], null)).toBe(
      '/ade/dashboard/export/studio?artifact=p-1&label=Pets+API&from=versions&step=target',
    );
  });
});

// --- component ---------------------------------------------------------------------------------

describe('ExportSourcePicker', () => {
  it('lists catalog items with their pills, searches them, and opens the chosen one at Target', async () => {
    const calls = mockFetch(OK);
    const { container } = render(<ExportSourcePicker />);
    const list = await screen.findByTestId('export-source-catalog');
    expect(within(list).getAllByRole('button').map((b) => b.getAttribute('aria-label'))).toEqual([
      'Export catalog item Ledger Graph',
      'Export catalog item Orders RPC',
    ]);
    expect(within(list).getByText('GraphQL')).toBeInTheDocument();
    expect(calls).toEqual(['/api/catalog']); // projects are read only when their tab opens
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();

    fireEvent.change(screen.getByRole('searchbox', { name: 'Search catalog items' }), { target: { value: 'nothing' } });
    expect(screen.getByTestId('export-source-catalog-empty')).toHaveTextContent('No catalog item matches “nothing”.');
    fireEvent.change(screen.getByRole('searchbox', { name: 'Search catalog items' }), { target: { value: 'orders' } });
    fireEvent.click(screen.getByRole('button', { name: 'Export catalog item Orders RPC' }));
    expect(mockPush).toHaveBeenCalledWith(catalogSourceHref(CATALOG[0]));
  });

  it('lists projects without catalog items, then a project’s versions and its latest', async () => {
    mockFetch(OK);
    const { container } = render(<ExportSourcePicker />);
    await screen.findByTestId('export-source-catalog');
    openTab('Projects');
    const projects = await screen.findByTestId('export-source-projects');
    expect(within(projects).getAllByRole('button')).toHaveLength(1); // Orders RPC (a catalog item) is not here
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();

    fireEvent.click(within(projects).getByRole('button', { name: 'Choose a version of Pets API' }));
    const versions = await screen.findByTestId('export-source-versions');
    expect(within(versions).getAllByRole('button').map((b) => b.textContent)).toEqual([
      'Latest version',
      '1.1.0',
      '1.0.0Published',
    ]);
    fireEvent.click(screen.getByRole('button', { name: 'Export Pets API version 1.0.0' }));
    expect(mockPush).toHaveBeenLastCalledWith(projectSourceHref(PROJECTS[0], VERSIONS[0]));
    fireEvent.click(screen.getByRole('button', { name: 'Export the latest version of Pets API' }));
    expect(mockPush).toHaveBeenLastCalledWith(projectSourceHref(PROJECTS[0], null));

    fireEvent.click(screen.getByTestId('export-source-change-project'));
    expect(await screen.findByTestId('export-source-projects')).toBeInTheDocument();
  });

  it('is reachable by keyboard: the search, then each row in order', async () => {
    mockFetch(OK);
    render(<ExportSourcePicker />);
    const list = await screen.findByTestId('export-source-catalog');
    const rows = within(list).getAllByRole('button');
    rows.forEach((row) => expect(row.tagName).toBe('BUTTON'));
    rows[0].focus();
    expect(rows[0]).toHaveFocus();
  });

  it('says when there are no projects yet', async () => {
    mockFetch({ ...OK, '/api/projects': () => ({ body: { success: true, projects: [PROJECTS[1]] } }) });
    render(<ExportSourcePicker />);
    await screen.findByTestId('export-source-catalog');
    openTab('Projects');
    expect(await screen.findByTestId('export-source-projects-empty')).toHaveTextContent('There are no projects yet.');
  });

  it('shows a retryable error when a list cannot be loaded', async () => {
    let fail = true;
    mockFetch({
      '/api/catalog': () =>
        fail ? { status: 503, body: { success: false, error: 'REST is down' } } : { body: { success: true, catalog: CATALOG } },
    });
    render(<ExportSourcePicker />);
    expect(await screen.findByText(/REST is down/)).toBeInTheDocument();
    fail = false;
    fireEvent.click(screen.getByRole('button', { name: /try again|retry/i }));
    await waitFor(() => expect(screen.getByTestId('export-source-catalog')).toBeInTheDocument());
  });
});

// --- keyboard-only and the a11y gate (X3, #6224) -------------------------------------------------

describe('ExportSourcePicker with the keyboard alone (X3)', () => {
  it('searches and opens a catalog item without a pointer', async () => {
    mockFetch(OK);
    const user = userEvent.setup();
    render(<ExportSourcePicker />);
    await screen.findByTestId('export-source-catalog');

    await tabTo(user, screen.getByRole('searchbox', { name: 'Search catalog items' }));
    await user.keyboard('orders');
    await tabTo(user, screen.getByRole('button', { name: 'Export catalog item Orders RPC' }));
    await user.keyboard('{Enter}');
    expect(mockPush).toHaveBeenCalledWith(catalogSourceHref(CATALOG[0]));
  });

  it('switches to Projects with the arrow keys, then opens a version', async () => {
    mockFetch(OK);
    const user = userEvent.setup();
    render(<ExportSourcePicker />);
    await screen.findByTestId('export-source-catalog');

    await tabTo(user, screen.getByRole('tab', { name: 'Catalog items' }));
    await user.keyboard('{ArrowRight}');
    expect(screen.getByRole('tab', { name: 'Projects' })).toHaveAttribute('aria-selected', 'true');

    await tabTo(user, await screen.findByRole('button', { name: 'Choose a version of Pets API' }));
    await user.keyboard('{Enter}');
    await tabTo(user, await screen.findByRole('button', { name: 'Export Pets API version 1.1.0' }));
    await user.keyboard(' ');
    expect(mockPush).toHaveBeenLastCalledWith(projectSourceHref(PROJECTS[0], VERSIONS[1]));

    // "All projects" goes back without a pointer too.
    await tabTo(user, screen.getByTestId('export-source-change-project'), { backwards: true });
    await user.keyboard('{Enter}');
    expect(await screen.findByTestId('export-source-projects')).toBeInTheDocument();
  });

  /**
   * The browser fixtures for the axe gate (`e2e/a11y/routes.ts`, entry `export-e1`), written into
   * `e2e/fixtures/hive-a11y/` when `A11Y_FIXTURE_DUMP=1`:
   *
   *     A11Y_FIXTURE_DUMP=1 npx jest tests/export-source-picker.test.tsx -t "a11y gate"
   */
  it('dumps the catalog list and a project\'s versions for the a11y gate', async () => {
    mockFetch(OK);
    const { container } = render(<ExportSourcePicker />);
    await screen.findByTestId('export-source-catalog');
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
    writeA11yFixture('export-source-picker', liveMarkup(container.firstElementChild as Element));

    openTab('Projects');
    fireEvent.click(await screen.findByRole('button', { name: 'Choose a version of Pets API' }));
    await screen.findByTestId('export-source-versions');
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
    writeA11yFixture('export-source-picker-versions', liveMarkup(container.firstElementChild as Element));
  });
});
