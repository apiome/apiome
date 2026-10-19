/**
 * Ownership on the Catalog — CDG-2.4 (#5963).
 *
 * The Catalog screen against a mocked `/api/catalog` that carries each item's `owner`, and mocked
 * `/api/teams` and `/api/owners/*`. Pinned:
 *
 * - filtering by team is **server-side**: choosing a team puts `?team=` in the URL, and the list read
 *   then asks the BFF for that team — the browser never narrows the rows itself;
 * - confirming a suggested owner from the table updates the row in place, with no second read;
 * - the bulk bar's **Assign owner** sends every selected item in one `owners:assign` call;
 * - the owner filter, the column and the bar pass axe, and the docs fixture `catalog-owner-filter`
 *   is dumped from the filtered table.
 */

import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { axe } from 'jest-axe';
import 'jest-axe/extend-expect';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';

const mockReplace = jest.fn();
let searchParams = new URLSearchParams();

jest.mock('@lib/auth/session-client', () => ({
  useAuthSession: () => ({
    data: { user: { user_id: 'u-ada', current_tenant_id: 't-acme', email: 'ada@acme.io' } },
    status: 'authenticated',
    update: jest.fn(),
  }),
  AuthSessionProvider: ({ children }: { children: React.ReactNode }) => children,
}));

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn(), replace: mockReplace }),
  useSearchParams: () => searchParams,
  usePathname: () => '/ade/dashboard/catalog',
}));

jest.mock('@/app/components/providers/DialogProvider', () => ({
  useDialog: () => ({ confirm: jest.fn(async () => true), alert: jest.fn(async () => undefined) }),
}));

jest.mock('@lib/db/helper', () => ({
  deleteProject: jest.fn(),
  restoreProject: jest.fn(),
  permanentDeleteProject: jest.fn(),
}));

jest.mock('@/app/components/ade/dashboard/catalog/CatalogImportDialog', () => ({
  __esModule: true,
  CatalogImportDialog: () => null,
}));
jest.mock('@/app/components/ade/dashboard/catalog/ConversionPreviewDialog', () => ({
  __esModule: true,
  ConversionPreviewDialog: () => null,
}));
jest.mock('@/app/components/ade/dashboard/catalog/CatalogLintReportDialog', () => ({
  __esModule: true,
  CatalogLintReportDialog: () => null,
}));
jest.mock('@/app/ade/dashboard/primitives/PrimitiveImportDialog', () => ({
  __esModule: true,
  default: () => null,
}));

import CatalogClient from '../src/app/ade/dashboard/catalog/CatalogClient';
import { writeA11yFixture } from './helpers/a11y-fixture-dump';

const PAYMENTS = { id: 't-1', slug: 'payments', name: 'Payments' };
const TEAMS = [
  { ...PAYMENTS, member_count: 3 },
  { id: 't-2', slug: 'platform', name: 'Platform', member_count: 5 },
];

const base = {
  tenant_id: 't-acme',
  creator_id: 'u-ada',
  enabled: true,
  deleted_at: null,
  created_at: '2026-06-01T10:00:00.000Z',
  updated_at: '2026-10-14T16:02:00.000Z',
  creator_name: 'Ada Lovelace',
  creator_email: 'ada@acme.io',
  versionsCount: 2,
  qualityScore: 88,
  qualityGrade: 'B',
  publishable: false,
  tags: [],
};

const LEDGER = {
  ...base,
  id: '4d1e9a00-0000-4000-8000-000000000001',
  name: 'Ledger events',
  slug: 'ledger-events',
  sourceFormat: 'asyncapi-3',
  protocol: 'event',
  formatMetadata: { inputKind: 'connector', connectorKind: 'kong-admin' },
  owner: { team: PAYMENTS, status: 'confirmed', source: 'manual' },
};
const REFUNDS = {
  ...base,
  id: '4d1e9a00-0000-4000-8000-000000000002',
  name: 'Refunds gRPC',
  slug: 'refunds-grpc',
  sourceFormat: 'protobuf',
  protocol: 'rpc',
  formatMetadata: { inputKind: 'file', fileName: 'refunds.proto' },
  owner: { team: PAYMENTS, status: 'suggested', source: 'gateway_tag' },
};
const CARDS = {
  ...base,
  id: '4d1e9a00-0000-4000-8000-000000000003',
  name: 'Card tokens',
  slug: 'card-tokens',
  sourceFormat: 'graphql',
  protocol: 'graph',
  formatMetadata: { inputKind: 'file', fileName: 'cards.graphql' },
  owner: { team: PAYMENTS, status: 'suggested', source: 'codeowners' },
};
const UNOWNED = {
  ...base,
  id: '4d1e9a00-0000-4000-8000-000000000004',
  name: 'Search index',
  slug: 'search-index',
  sourceFormat: 'graphql',
  protocol: 'graph',
  formatMetadata: { inputKind: 'file', fileName: 'search.graphql' },
  owner: null,
};

let calls: Array<{ url: string; method: string; body: unknown }> = [];

function mockFetch() {
  global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? 'GET';
    calls.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : null });
    const reply = (body: unknown) => ({ ok: true, status: 200, statusText: 'OK', json: async () => body }) as Response;
    if (url === '/api/teams') return reply({ teams: TEAMS, count: TEAMS.length });
    if (url.startsWith('/api/import/sources')) return reply({ success: true, sources: [] });
    if (url.endsWith('/confirm')) {
      return reply({ owner: { team: PAYMENTS, status: 'confirmed', source: 'gateway_tag' }, suggestions: [] });
    }
    if (url === '/api/owners/assign') return reply({ results: [], count: (init?.body ? JSON.parse(String(init.body)).entities.length : 0) });
    // The server applies `?team=`; here every row already belongs to Payments but one.
    const team = new URL(url, 'http://ui.test').searchParams.get('team');
    const rows = [LEDGER, REFUNDS, CARDS, UNOWNED].filter((row) => !team || row.owner?.team.slug === team);
    return reply({ success: true, catalog: rows });
  }) as unknown as typeof fetch;
}

beforeEach(() => {
  jest.clearAllMocks();
  window.localStorage.clear();
  searchParams = new URLSearchParams();
  calls = [];
  mockFetch();
});

async function renderTable() {
  render(<CatalogClient />);
  await screen.findAllByText('Ledger events');
  fireEvent.click(screen.getByTestId('catalog-view-table'));
  await screen.findByTestId('catalog-table');
}

// The catalog-item list read; the kinds summary (`/api/catalog/entities…`, CDG-5.1) is a separate read.
const catalogReads = () =>
  calls.filter((call) => call.url.startsWith('/api/catalog') && !call.url.startsWith('/api/catalog/entities'));

test('choosing a team puts it in the URL, and the read asks the server for it', async () => {
  const user = userEvent.setup();
  await renderTable();
  await waitFor(() => expect(screen.getByRole('option', { name: 'Platform' })).toBeInTheDocument());
  await user.selectOptions(screen.getByTestId('catalog-owner-filter'), 'payments');
  expect(mockReplace).toHaveBeenCalledWith('?team=payments', { scroll: false });
});

test('?team= is forwarded to the BFF, which REST filters', async () => {
  searchParams = new URLSearchParams('team=payments');
  await renderTable();
  expect(catalogReads().at(-1)?.url).toBe('/api/catalog?team=payments');
  expect(screen.queryByText('Search index')).not.toBeInTheDocument();
});

test('the Owner column shows confirmed and suggested owners, and confirming updates the row in place', async () => {
  const user = userEvent.setup();
  await renderTable();
  const table = screen.getByTestId('catalog-table');
  expect(within(table).getByTestId(`catalog-owner-${LEDGER.id}`)).toHaveTextContent('Payments');
  expect(within(table).getByTestId(`catalog-owner-${UNOWNED.id}`)).toHaveTextContent('No owner');
  const refunds = within(table).getByTestId(`catalog-owner-${REFUNDS.id}`);
  expect(refunds).toHaveTextContent('Suggested · Gateway tag');

  const reads = catalogReads().length;
  await user.click(within(table).getByTestId(`catalog-owner-${REFUNDS.id}-confirm`));
  await waitFor(() =>
    expect(within(table).getByTestId(`catalog-owner-${REFUNDS.id}`)).toHaveAttribute('data-status', 'confirmed')
  );
  expect(catalogReads()).toHaveLength(reads);
  expect(calls.find((call) => call.url.endsWith('/confirm'))?.url).toBe(`/api/owners/catalog_item/${REFUNDS.id}/confirm`);
});

test('the bulk bar assigns one team to every selected item in one call', async () => {
  const user = userEvent.setup();
  await renderTable();
  const table = screen.getByTestId('catalog-table');
  await user.click(within(table).getByRole('checkbox', { name: /Select Refunds gRPC/ }));
  await user.click(within(table).getByRole('checkbox', { name: /Select Search index/ }));
  await user.selectOptions(screen.getByTestId('bulk-owner-team'), 'platform');
  await user.click(screen.getByTestId('bulk-assign-owner'));
  await waitFor(() => expect(calls.some((call) => call.url === '/api/owners/assign')).toBe(true));
  expect(calls.find((call) => call.url === '/api/owners/assign')?.body).toEqual({
    team: 'platform',
    entities: [
      { kind: 'catalog_item', id: REFUNDS.id },
      { kind: 'catalog_item', id: UNOWNED.id },
    ],
  });
});

test('the filtered table passes axe, and is the docs fixture', async () => {
  searchParams = new URLSearchParams('team=payments');
  const { container } = render(<CatalogClient />);
  await screen.findAllByText('Ledger events');
  fireEvent.click(screen.getByTestId('catalog-view-table'));
  await screen.findByTestId('catalog-table');
  await waitFor(() => expect(screen.getByRole('option', { name: 'Payments' })).toBeInTheDocument());
  expect(await axe(container)).toHaveNoViolations();
  // `outerHTML` carries attributes, not a select's live value: mark the chosen team so the
  // fixture (and its screenshot) shows the filter applied.
  screen.getByRole('option', { name: 'Payments' }).setAttribute('selected', '');
  writeA11yFixture('catalog-owner-filter', (document.querySelector('.page') ?? container.firstElementChild)!.outerHTML);
});
