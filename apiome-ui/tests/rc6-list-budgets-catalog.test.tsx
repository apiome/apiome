/**
 * The Catalog at 1,000 items — RC6-H6 (#6213).
 *
 * A realistic tenant has a thousand catalog items. The Catalog draws one page of them
 * (`CATALOG_PAGE_SIZE`), so the first row, a filter keystroke and a re-sort cost the same at a
 * thousand as at fifty. This suite renders the real screen with 1,000 items in jsdom, checks it
 * mounts one page, and times each step against `tests/helpers/list-budgets.ts`.
 */

import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';

let mockRole = 'owner';

jest.mock('../src/app/components/ade/access/useMyPermissions', () => ({
  ...jest.requireActual('../src/app/components/ade/access/useMyPermissions'),
  useMyPermissions: () => jest.requireActual<typeof import('./helpers/permission-matrix')>('./helpers/permission-matrix').permissionsFor(mockRole),
}));

jest.mock('@lib/auth/session-client', () => ({
  useAuthSession: () => ({
    data: { user: { user_id: 'u-ada', current_tenant_id: 't-acme', email: 'ada@acme.io' } },
    status: 'authenticated',
    update: jest.fn(),
  }),
  AuthSessionProvider: ({ children }: { children: React.ReactNode }) => children,
}));

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn(), replace: jest.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => '/ade/dashboard/catalog',
}));

jest.mock('@/app/components/providers/DialogProvider', () => ({
  useDialog: () => ({ confirm: jest.fn(async () => true), alert: jest.fn(async () => undefined) }),
}));

jest.mock('@lib/db/helper-actions', () => ({
  deleteProject: jest.fn(async () => JSON.stringify({ success: true })),
  restoreProject: jest.fn(async () => JSON.stringify({ success: true })),
  permanentDeleteProject: jest.fn(async () => JSON.stringify({ success: true })),
}));

jest.mock('@/app/components/ade/dashboard/catalog/CatalogImportDialog', () => ({
  __esModule: true,
  CatalogImportDialog: () => null,
}));

jest.mock('@/app/components/ade/dashboard/catalog/ConversionPreviewDialog', () => ({
  __esModule: true,
  ConversionPreviewDialog: () => null,
}));

import CatalogClient from '../src/app/ade/dashboard/catalog/CatalogClient';
import { CATALOG_PAGE_SIZE } from '../src/app/components/ade/catalog/catalogModel';
import { CATALOG_VIEW_PREFS_STORAGE_KEY } from '../src/app/utils/catalog-view-preferences';
import { LIST_BUDGET_MS, timed, writeAtSizeFixture } from './helpers/list-budgets';

const BASE = {
  tenant_id: 't-acme',
  creator_id: 'u-ada',
  description: 'A catalog item.',
  enabled: true,
  deleted_at: null,
  created_at: '2026-06-01T10:00:00.000Z',
  updated_at: '2026-08-14T16:02:00.000Z',
  creator_name: 'Ada Lovelace',
  creator_email: 'ada@acme.io',
  versionsCount: 3,
  qualityScore: 81,
  qualityGrade: 'B',
  sourceFormat: 'graphql',
  protocol: 'graph',
  formatMetadata: { inputKind: 'file', fileName: 'item.graphql' },
  conversion: null,
  paradigm: 'graph',
  domain: 'finance',
  tags: ['internal'],
};

/** A thousand items, `Item 0000` … `Item 0999`. */
const ITEMS = Array.from({ length: 1000 }, (_, index) => ({
  ...BASE,
  id: `00000000-0000-4000-8000-${String(index).padStart(12, '0')}`,
  name: `Item ${String(index).padStart(4, '0')}`,
  slug: `item-${index}`,
}));

/** The cards and rows on screen. */
function drawn(): number {
  return document.querySelectorAll('[data-testid="catalog-card"], [data-testid="catalog-table"] tbody tr[data-row-id]')
    .length;
}

/** Mount the Catalog over these items and wait for the first one. */
async function mount(items: readonly unknown[]) {
  global.fetch = jest.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.startsWith('/api/import/sources')) {
      return { ok: true, statusText: 'OK', json: async () => ({ success: true, sources: [] }) } as Response;
    }
    return { ok: true, statusText: 'OK', json: async () => ({ success: true, catalog: items }) } as Response;
  }) as unknown as typeof fetch;
  render(<CatalogClient />);
  await screen.findByText('Item 0000');
}

/** Filter by `term` and wait until `expected` is listed and Item 0000 is gone. */
async function filterTo(term: string, expected: string) {
  fireEvent.change(screen.getByPlaceholderText(/Filter catalog/), { target: { value: term } });
  await screen.findByText(expected);
  await waitFor(() => expect(screen.queryByText('Item 0000')).toBeNull());
}

/** Fifty items, for the warm-up mount. */
const ONE_PAGE = ITEMS.slice(0, CATALOG_PAGE_SIZE);

beforeEach(() => {
  mockRole = 'owner';
  window.localStorage.clear();
});

describe.each(['cards', 'table'] as const)('the Catalog %s view at 1,000 items', (view) => {
  beforeEach(() => {
    if (view === 'table') {
      window.localStorage.setItem(CATALOG_VIEW_PREFS_STORAGE_KEY, JSON.stringify({ viewMode: 'table' }));
    }
  });

  it('mounts one page of a thousand items, and draws its first row within budget', async () => {
    await mount(ONE_PAGE); // warm-up: the first mount in a worker pays for module setup
    cleanup();
    const ms = await timed(() => mount(ITEMS));
    expect(ms).toBeLessThan(LIST_BUDGET_MS.firstRow);
    if (view === 'table') expect(screen.getByTestId('catalog-table')).toBeInTheDocument();
    expect(drawn()).toBe(CATALOG_PAGE_SIZE);
    expect(screen.getByText(/Showing 1–50 of 1000 items/)).toBeInTheDocument();
  });

  it('filters within budget, still drawing one page', async () => {
    await mount(ITEMS);
    // `Item 09` leaves Item 0900–0999: a hundred of a thousand, one page drawn.
    const ms = await timed(() => filterTo('Item 09', 'Item 0900'));
    expect(ms).toBeLessThan(LIST_BUDGET_MS.filter);
    expect(drawn()).toBe(CATALOG_PAGE_SIZE);
    expect(screen.getByText(/Showing 1–50 of 100 items/)).toBeInTheDocument();
  });

  it('pages, and starts again at page 1 when the list narrows', async () => {
    await mount(ITEMS);
    const pager = screen.getByRole('navigation', { name: 'Catalog pages' });
    fireEvent.click(within(pager).getByRole('button', { name: 'Page 2' }));
    await screen.findByText('Item 0050');
    expect(screen.queryByText('Item 0000')).toBeNull();
    fireEvent.change(screen.getByPlaceholderText(/Filter catalog/), { target: { value: 'Item 00' } });
    await screen.findByText('Item 0000');
    expect(screen.getByText(/Showing 1–50 of 100 items/)).toBeInTheDocument();
  });
});

describe('sorting the Catalog table at 1,000 items', () => {
  it('re-sorts within budget, still drawing one page', async () => {
    // The table, sorted by name ascending — written before each mount, because the screen saves
    // the sort a click chooses.
    const tableByName = () =>
      window.localStorage.setItem(CATALOG_VIEW_PREFS_STORAGE_KEY, JSON.stringify({ viewMode: 'table' }));
    // One click on Artifact turns the order to descending.
    const resort = (last: string) => async () => {
      fireEvent.click(screen.getByRole('button', { name: /^Artifact/ }));
      await screen.findByText(last);
    };
    tableByName();
    await mount(ITEMS);
    const ms = await timed(resort('Item 0999'));
    expect(ms).toBeLessThan(LIST_BUDGET_MS.sort);
    expect(drawn()).toBe(CATALOG_PAGE_SIZE);
  });
});

describe('the at-size fixtures', () => {
  // A returning reader, as the parity fixture (`hive-catalog/table.html`) is: the first-visit
  // explainer dismissed, so the dumps measure the list, not the welcome.
  beforeEach(() => window.localStorage.setItem('hive.seen.catalog-explainer', '1'));

  it('renders the fixture the browser spec measures for each view', async () => {
    await mount(ITEMS);
    writeAtSizeFixture('catalog-cards-1000');
    fireEvent.click(screen.getByTestId('catalog-view-table'));
    await screen.findByTestId('catalog-table');
    writeAtSizeFixture('catalog-table-1000');
  });

  it('renders the same cards view with three items, the baseline the cards are compared with', async () => {
    await mount(ITEMS.slice(0, 3));
    writeAtSizeFixture('catalog-cards-3');
  });
});
