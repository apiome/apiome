/**
 * The Catalog redesign, rendered (HIVE-7.1, #5318).
 *
 * `catalog-model.test.ts` holds the decisions and `catalog-css.test.ts` pins the declarations;
 * this holds the screen that makes them, against a mocked `/api/catalog` returning the
 * documented `{success, catalog}` envelope. What it pins is the ticket's four acceptance
 * criteria and the mockup's **Notes → Keeps (1:1)** list:
 *
 *   1. **Every format in the registry keeps a stable pill hue.** The pill is `FormatPill`, so
 *      the hue is the fixed identity block — asserted by reading `data-format` off the pill in
 *      both views and finding the same `.fmt--*` class.
 *   2. **Facet counts reflect the active filter set; "Clear all filters" restores.**
 *   3. **The identity-group chip works**, and clearing it goes back to the whole catalog.
 *   4. **The import wizard is the 6.4 component**, opened from the header and from the empty
 *      state.
 *
 * Plus the four things the screen this replaces got wrong and this ticket fixes: the card was
 * a `role="button"` full of buttons, a failed read looked like an empty catalog, a permanent
 * delete was two identical native confirms, and there was no way to act on the list in bulk.
 */

import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { axe } from 'jest-axe';
import 'jest-axe/extend-expect';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';
import * as fs from 'fs';
import * as path from 'path';

const mockPush = jest.fn();
const mockConfirm = jest.fn<Promise<boolean>, [unknown]>(() => Promise.resolve(true));
const mockAlert = jest.fn<Promise<void>, [unknown]>(() => Promise.resolve());
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
  useRouter: () => ({ push: mockPush, replace: jest.fn() }),
  useSearchParams: () => searchParams,
  usePathname: () => '/ade/dashboard/catalog',
}));

jest.mock('@/app/components/providers/DialogProvider', () => ({
  useDialog: () => ({
    confirm: (options: unknown) => mockConfirm(options),
    alert: (options: unknown) => mockAlert(options),
  }),
}));

const mockDeleteProject = jest.fn(async () => JSON.stringify({ success: true }));
const mockRestoreProject = jest.fn(async () => JSON.stringify({ success: true }));
const mockPermanentDelete = jest.fn(async () => JSON.stringify({ success: true }));

jest.mock('@lib/db/helper', () => ({
  deleteProject: (...args: unknown[]) => mockDeleteProject(...(args as [])),
  restoreProject: (...args: unknown[]) => mockRestoreProject(...(args as [])),
  permanentDeleteProject: (...args: unknown[]) => mockPermanentDelete(...(args as [])),
}));

/** The four overlays are whole screens of their own, and not under test here. */
jest.mock('@/app/components/ade/dashboard/catalog/CatalogImportDialog', () => ({
  __esModule: true,
  CatalogImportDialog: ({ open }: { open: boolean }) =>
    open ? <div data-testid="catalog-import-dialog">import wizard</div> : null,
}));

jest.mock('@/app/components/ade/dashboard/catalog/ConversionPreviewDialog', () => ({
  __esModule: true,
  ConversionPreviewDialog: ({ open }: { open: boolean }) =>
    open ? <div data-testid="catalog-convert-dialog">conversion preview</div> : null,
}));

jest.mock('@/app/components/ade/dashboard/catalog/CatalogLintReportDialog', () => ({
  __esModule: true,
  CatalogLintReportDialog: ({ open }: { open: boolean }) =>
    open ? <div data-testid="catalog-lint-dialog">lint report</div> : null,
}));

jest.mock('@/app/ade/dashboard/primitives/PrimitiveImportDialog', () => ({
  __esModule: true,
  default: () => <div data-testid="primitive-import-dialog">types import</div>,
}));

import CatalogClient from '../src/app/ade/dashboard/catalog/CatalogClient';
import { CATALOG_VIEW_PREFS_STORAGE_KEY } from '../src/app/utils/catalog-view-preferences';

// ---------------------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------------------

const LEDGER = {
  id: '4d1e9a00-0000-4000-8000-000000000001',
  tenant_id: 't-acme',
  creator_id: 'u-ada',
  name: 'Ledger Graph',
  slug: 'ledger-graph',
  description: 'Double-entry ledger schema exposed to finance tooling.',
  enabled: true,
  deleted_at: null,
  created_at: '2026-06-01T10:00:00.000Z',
  updated_at: '2026-08-14T16:02:00.000Z',
  creator_name: 'Ada Lovelace',
  creator_email: 'ada@acme.io',
  versionsCount: 3,
  qualityScore: 91,
  qualityGrade: 'A',
  publishable: false,
  sourceFormat: 'graphql',
  protocol: 'graph',
  formatMetadata: { inputKind: 'file', fileName: 'ledger.graphql' },
  conversion: { projectId: 'p-ledger', projectName: 'Ledger Graph (OpenAPI)' },
};

const ORDERS = {
  ...LEDGER,
  id: '7c21e900-0000-4000-8000-000000000002',
  name: 'Orders RPC',
  slug: 'orders-rpc',
  description: 'Order lifecycle service, as protobuf.',
  versionsCount: 2,
  qualityScore: 74,
  qualityGrade: 'C',
  sourceFormat: 'protobuf',
  protocol: 'rpc',
  formatMetadata: { inputKind: 'url', sourceUrl: 'https://acme.io/orders.proto' },
  conversion: null,
};

const EVENTS = {
  ...LEDGER,
  id: 'b00b1e00-0000-4000-8000-000000000003',
  name: 'Events Bus',
  slug: 'events-bus',
  description: 'Domain events published to the bus.',
  enabled: false,
  versionsCount: 1,
  qualityScore: null,
  qualityGrade: null,
  sourceFormat: 'asyncapi',
  protocol: 'event',
  formatMetadata: { inputKind: 'paste' },
  conversion: null,
};

const RETIRED = {
  ...LEDGER,
  id: 'deadbe00-0000-4000-8000-000000000004',
  name: 'Legacy Graph',
  slug: 'legacy-graph',
  description: 'Superseded graph, kept for reference.',
  deleted_at: '2026-08-10T09:00:00.000Z',
  versionsCount: 1,
  qualityScore: 58,
  qualityGrade: 'D',
  conversion: null,
};

const ALL_ROWS = [LEDGER, ORDERS, EVENTS, RETIRED];

/**
 * The registry `useCatalogImportAvailability` reads, with one adapter that cannot run here.
 *
 * Wide enough that "How the catalog works" draws a full row of pills and a "+n more", which is
 * what the `about` fixture (and the docs screenshot made from it) should show.
 */
const IMPORT_SOURCES = [
  ...[
    'graphql', 'asyncapi', 'thrift', 'avro', 'raml', 'wsdl', 'wit', 'postman', 'mcp', 'edix12',
    'cobolcopybook', 'smithy', 'odata', 'xsd', 'openrpc', 'cloudevents', 'apiblueprint',
    'typespec', 'hl7v2', 'fhir',
  ].map((key) => ({ key, label: key, available: true, input_kinds: ['file', 'url', 'paste'] })),
  {
    // `catalogAdapterForFormat('protobuf').sourceKind` is `grpc`, which is the key the
    // availability lookup is made on.
    key: 'grpc',
    label: 'gRPC / Protobuf',
    available: false,
    unavailable_reason: 'buf is not installed in this runtime',
    input_kinds: ['file'],
  },
];

/** Serve `/api/catalog`, honouring the `include_deleted` parameter the switch adds. */
function mockCatalog(rows: readonly unknown[] = ALL_ROWS, options: { fail?: boolean } = {}) {
  global.fetch = jest.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.startsWith('/api/import/sources')) {
      return { ok: true, statusText: 'OK', json: async () => ({ success: true, sources: IMPORT_SOURCES }) } as Response;
    }
    if (options.fail) {
      return { ok: false, statusText: 'Service Unavailable', json: async () => ({}) } as Response;
    }
    const includeDeleted = url.includes('include_deleted=true');
    const catalog = includeDeleted
      ? rows
      : rows.filter((row) => !(row as { deleted_at: string | null }).deleted_at);
    return { ok: true, statusText: 'OK', json: async () => ({ success: true, catalog }) } as Response;
  }) as unknown as typeof fetch;
}

/** Render the screen and wait for the first read to land. */
async function renderCatalog(
  rows: readonly unknown[] = ALL_ROWS,
  options: { fail?: boolean } = {}
) {
  mockCatalog(rows, options);
  const user = userEvent.setup();
  render(<CatalogClient />);
  await waitFor(() => expect(global.fetch).toHaveBeenCalled());
  return { user };
}

/** Radix `DropdownMenu.Trigger` opens on `pointerdown`, which jsdom does not synthesise. */
function openMenu(trigger: HTMLElement) {
  fireEvent.keyDown(trigger, { key: 'Enter' });
}

/** Switch to the table view, which needs the segmented control's own value change. */
async function showTable() {
  fireEvent.click(screen.getByTestId('catalog-view-table'));
  await screen.findByTestId('catalog-table');
}

beforeEach(() => {
  jest.clearAllMocks();
  window.localStorage.clear();
  searchParams = new URLSearchParams();
  mockConfirm.mockImplementation(() => Promise.resolve(true));
});

// ---------------------------------------------------------------------------------------
// The page
// ---------------------------------------------------------------------------------------

describe('the page', () => {
  it('draws the header, the breadcrumb and the description with its ghost link', async () => {
    await renderCatalog();
    expect(await screen.findByRole('heading', { name: 'Catalog', level: 1 })).toBeInTheDocument();
    const trail = screen.getByRole('navigation', { name: /breadcrumb/i });
    expect(trail).toHaveTextContent('Home');
    expect(trail).toHaveTextContent('Bring in');
    expect(
      screen.getByText(/Non-OpenAPI specs, stored as-is and converted only when you’re ready\./)
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'How the catalog works' })).toBeInTheDocument();
  });

  it('folds the stat strip into one facts line, every figure present', async () => {
    await renderCatalog();
    const facts = await screen.findByRole('list', { name: 'Catalog summary' });
    await waitFor(() => expect(facts).toHaveTextContent('3 items'));
    // Three live items, three formats, the mean of 91 and 74, one conversion, one disabled.
    expect(facts).toHaveTextContent('3 formats');
    expect(facts).toHaveTextContent('avg quality B · 83');
    expect(facts).toHaveTextContent('1 converted to OpenAPI');
    expect(facts).toHaveTextContent('2 active · 1 disabled');
    expect(within(facts).getAllByTestId('format-pill').length).toBe(3);
  });

  it('reveals the unchanged stat strip in place, and remembers the choice', async () => {
    await renderCatalog();
    const toggle = await screen.findByRole('button', { name: 'Show stats' });
    expect(screen.getByTestId('catalog-stats-row').closest('[hidden]')).not.toBeNull();
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByTestId('catalog-stats-row').closest('[hidden]')).toBeNull();
    expect(screen.getByTestId('catalog-stat-items')).toHaveTextContent('3');
    expect(window.localStorage.getItem('hive.catalog.stats')).toBe('1');
  });

  it('shows the explainer once, as a note, and keeps it reachable after Got it', async () => {
    await renderCatalog();
    const note = await screen.findByRole('note');
    expect(note.textContent).toContain('Catalog items are non-publishable.');
    fireEvent.click(within(note).getByRole('button', { name: 'Got it' }));
    expect(screen.queryByRole('note')).not.toBeInTheDocument();
    expect(window.localStorage.getItem('hive.seen.catalog-explainer')).toBe('1');

    // The header link still opens the same explanation.
    fireEvent.click(screen.getByRole('button', { name: 'How the catalog works' }));
    const dialog = await screen.findByRole('dialog', { name: 'How the catalog works' });
    expect(within(dialog).getByText('They are not publishable until converted')).toBeInTheDocument();
  });

  it('opens the dialog from the callout’s Learn more, with the supported formats', async () => {
    await renderCatalog();
    const note = await screen.findByRole('note');
    fireEvent.click(within(note).getByRole('button', { name: 'Learn more' }));
    const dialog = await screen.findByRole('dialog', { name: 'How the catalog works' });
    expect(within(dialog).getByText('Supported import formats')).toBeInTheDocument();
    // The adapter the registry says cannot run here is not counted as importable.
    await waitFor(() =>
      expect(within(dialog).getByTestId('catalog-about-counts')).toHaveTextContent(
        /unavailable here/
      )
    );
  });

  it('no longer stands the formats card or the banner above the list', async () => {
    await renderCatalog();
    await screen.findByText('Ledger Graph');
    expect(screen.queryByTestId('catalog-supported-formats')).not.toBeInTheDocument();
    expect(screen.queryByTestId('catalog-nonpublishable-banner')).not.toBeInTheDocument();
  });

  it('reads "0 items" with no stats toggle on an empty catalog, so the empty state leads', async () => {
    await renderCatalog([]);
    expect(await screen.findByText('Your catalog is empty')).toBeInTheDocument();
    expect(screen.getByRole('list', { name: 'Catalog summary' })).toHaveTextContent('0 items');
    expect(screen.queryByRole('button', { name: 'Show stats' })).not.toBeInTheDocument();
    expect(screen.queryByTestId('catalog-stats-row')).not.toBeInTheDocument();
    // The empty state is drawn inside the list's one card.
    expect(within(screen.getByTestId('catalog-cards')).getByText('Your catalog is empty')).toBeInTheDocument();
  });

  it('puts the filters, the view switch, the chips and the list in one card', async () => {
    await renderCatalog();
    await screen.findByText('Ledger Graph');
    const card = screen.getByTestId('catalog-cards');
    const filterRow = within(card).getByTestId('catalog-toolbar');
    expect(within(filterRow).getByTestId('catalog-view-table')).toBeInTheDocument();
    expect(within(card).getByTestId('catalog-views')).toBeInTheDocument();
    expect(within(card).getAllByTestId('catalog-card')).toHaveLength(3);

    await showTable();
    const table = screen.getByTestId('catalog-table');
    expect(within(table).getByTestId('catalog-toolbar')).toBeInTheDocument();
    expect(within(table).getByTestId('catalog-views')).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------------------
// The two views
// ---------------------------------------------------------------------------------------

describe('the two views draw one list', () => {
  it('renders a card per item, grouped by paradigm', async () => {
    await renderCatalog();
    await screen.findByText('Ledger Graph');
    expect(screen.getAllByTestId('catalog-card')).toHaveLength(3);
    expect(screen.getByTestId('catalog-paradigm-group-graph')).toHaveTextContent('Graph');
    expect(screen.getByTestId('catalog-paradigm-group-rpc')).toHaveTextContent('RPC');
    expect(screen.getByTestId('catalog-paradigm-group-event')).toHaveTextContent('Event');
  });

  it('drops the paradigm sections when grouping is off', async () => {
    await renderCatalog();
    await screen.findByText('Ledger Graph');
    fireEvent.click(screen.getByTestId('catalog-group-none'));
    expect(screen.queryByTestId('catalog-paradigm-group-graph')).not.toBeInTheDocument();
    expect(screen.getAllByTestId('catalog-card')).toHaveLength(3);
  });

  it('carries the same rows and the same format hue into the table', async () => {
    await renderCatalog();
    const cardPill = (await screen.findAllByTestId('format-pill')).find(
      (pill) => pill.getAttribute('data-format') === 'graphql'
    );
    expect(cardPill).toBeDefined();
    const hue = [...cardPill!.classList].find((name) => name.startsWith('fmt--'));
    expect(hue).toBeTruthy();

    await showTable();
    const rowPill = screen
      .getAllByTestId('format-pill')
      .find((pill) => pill.getAttribute('data-format') === 'graphql');
    expect(rowPill).toBeDefined();
    // The same identity class in both views — the ticket's first acceptance criterion.
    expect(rowPill!.classList.contains(hue!)).toBe(true);
  });

  it('draws the table’s nine columns in the mockup’s order', async () => {
    await renderCatalog();
    await screen.findByText('Ledger Graph');
    await showTable();
    const headers = within(screen.getByTestId('catalog-table'))
      .getAllByRole('columnheader')
      .map((cell) => cell.textContent?.trim());
    expect(headers).toEqual([
      '',
      'Artifact',
      'Format',
      'Protocol',
      'Source',
      'Quality',
      'Grade',
      'Status',
      'Updated',
      // The actions column has no visible label, but it is named for assistive tech.
      'Actions',
    ]);
  });

  it('states what is on screen and how it is ordered, in the table foot', async () => {
    await renderCatalog();
    await screen.findByText('Ledger Graph');
    await showTable();
    expect(screen.getByTestId('catalog-table-foot')).toHaveTextContent(
      '3 items · sorted by artifact ↑'
    );
  });
});

// ---------------------------------------------------------------------------------------
// The card
// ---------------------------------------------------------------------------------------

describe('the card', () => {
  it('is not a button full of buttons', async () => {
    await renderCatalog();
    const card = (await screen.findAllByTestId('catalog-card'))[0];
    // `nested-interactive` is a serious axe violation and the definition of done asks for
    // none: the card is an <article> whose *name* is the one link, stretched over it.
    expect(card.tagName).toBe('ARTICLE');
    expect(card).not.toHaveAttribute('role');
    expect(card).not.toHaveAttribute('tabindex');
    const link = within(card).getByRole('link', { name: 'Ledger Graph' });
    expect(link).toHaveAttribute('href', `/ade/dashboard/catalog/${LEDGER.id}`);
  });

  it('prints the identity, the provenance, the orbs and the revision count', async () => {
    await renderCatalog();
    const card = (await screen.findAllByTestId('catalog-card'))[0];
    expect(within(card).getByText(/cat_4d1e9a · ledger-graph/)).toBeInTheDocument();
    expect(within(card).getByTestId('catalog-card-status')).toHaveTextContent('Active');
    expect(within(card).getByTestId('catalog-card-versions')).toHaveTextContent('3 versions');
    const formats = within(card).getByTestId('catalog-card-formats');
    expect(within(formats).getByTestId('format-pill')).toHaveTextContent('GraphQL');
    expect(within(formats).getByTestId('source-badge')).toHaveTextContent('ledger.graphql');
    // Quality and Lint are buttons; Debt never is — it is not computed yet.
    expect(within(card).getByRole('button', { name: /Quality/ })).toBeInTheDocument();
    expect(within(card).queryByRole('button', { name: /Debt/ })).not.toBeInTheDocument();
  });

  it('links a converted item to the project it produced', async () => {
    await renderCatalog();
    const card = (await screen.findAllByTestId('catalog-card'))[0];
    const badge = within(card).getByTestId('catalog-converted-badge');
    expect(badge).toHaveTextContent('Converted →');
    expect(within(badge).getByRole('link', { name: 'Ledger Graph (OpenAPI)' })).toBeInTheDocument();
  });

  it('says "Format pending" once rather than three dashes', async () => {
    await renderCatalog([{ ...ORDERS, sourceFormat: null, protocol: null, formatMetadata: null }]);
    const card = (await screen.findAllByTestId('catalog-card'))[0];
    expect(within(card).getByText('Format pending')).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------------------
// Narrowing
// ---------------------------------------------------------------------------------------

describe('narrowing', () => {
  it('filters by search across both views', async () => {
    const { user } = await renderCatalog();
    await screen.findByText('Ledger Graph');
    await user.type(screen.getByTestId('catalog-search'), 'orders');
    await waitFor(() => expect(screen.getAllByTestId('catalog-card')).toHaveLength(1));
    expect(screen.getByText('Orders RPC')).toBeInTheDocument();
  });

  it('counts each chip over the rows the other controls left', async () => {
    await renderCatalog();
    await screen.findByText('Ledger Graph');
    expect(screen.getByTestId('catalog-facet-all')).toHaveTextContent('3');
    expect(screen.getByTestId('catalog-facet-active')).toHaveTextContent('2');
    expect(screen.getByTestId('catalog-facet-attention')).toHaveTextContent('1');
  });

  it('gates the Deleted chip on the switch that reveals deleted rows', async () => {
    await renderCatalog();
    await screen.findByText('Ledger Graph');
    const chip = screen.getByTestId('catalog-facet-deleted');
    expect(chip).toBeDisabled();
    expect(chip).toHaveAttribute('title', 'Turn on Show deleted to use this view');

    fireEvent.click(screen.getByLabelText('Show soft-deleted catalog items in the list'));
    await screen.findByText('Legacy Graph');
    expect(screen.getByTestId('catalog-facet-deleted')).not.toBeDisabled();
  });

  it('offers only the formats present, with the count ticking each would leave', async () => {
    await renderCatalog();
    await screen.findByText('Ledger Graph');
    openMenu(screen.getByTestId('catalog-format-facet'));
    const menu = await screen.findByTestId('catalog-format-facet-menu');
    expect(within(menu).getByTestId('catalog-format-option-graphql')).toHaveTextContent('1');
    expect(within(menu).getByTestId('catalog-format-option-protobuf')).toHaveTextContent('1');
    expect(within(menu).getByTestId('catalog-format-option-asyncapi')).toHaveTextContent('1');
  });

  it('narrows to a ticked format and restores on Clear all filters', async () => {
    await renderCatalog();
    await screen.findByText('Ledger Graph');
    openMenu(screen.getByTestId('catalog-format-facet'));
    fireEvent.click(await screen.findByTestId('catalog-format-option-asyncapi'));
    await waitFor(() => expect(screen.getAllByTestId('catalog-card')).toHaveLength(1));
    expect(screen.getByText('Events Bus')).toBeInTheDocument();

    // Narrow to nothing, then clear.
    fireEvent.click(screen.getByTestId('catalog-facet-active'));
    const empty = await screen.findByText('No catalog items match your filters or search');
    expect(empty).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('catalog-clear-filters'));
    await waitFor(() => expect(screen.getAllByTestId('catalog-card')).toHaveLength(3));
  });

  it('offers the three quick filters the mockup draws', async () => {
    await renderCatalog();
    await screen.findByText('Ledger Graph');
    expect(screen.getByTestId('catalog-filter-protocol')).toHaveTextContent('All protocols');
    expect(screen.getByTestId('catalog-filter-source')).toHaveTextContent('All sources');
    expect(screen.getByTestId('catalog-filter-grade')).toHaveTextContent('Any grade');
    for (const id of ['protocol', 'source', 'grade']) {
      expect(screen.getByTestId(`catalog-filter-${id}`)).not.toHaveAttribute('data-active');
    }
  });

  it('renders the identity-group filter as a dismissible chip, not a banner', async () => {
    searchParams = new URLSearchParams('identityGroupId=idg_7c21e9aa');
    await renderCatalog();
    const chip = await screen.findByTestId('catalog-identity-group-chip');
    expect(chip).toHaveTextContent('Identity group idg_7c21…');
    const catalogCall = (global.fetch as jest.Mock).mock.calls
      .map((call) => String(call[0]))
      .find((url) => url.startsWith('/api/catalog'));
    expect(catalogCall).toContain('identityGroupId=idg_7c21e9aa');
    fireEvent.click(chip);
    expect(mockPush).toHaveBeenCalledWith('/ade/dashboard/catalog');
  });
});

// ---------------------------------------------------------------------------------------
// Writes
// ---------------------------------------------------------------------------------------

describe('the three writes', () => {
  it('soft-deletes without a gate, and says how to get the item back', async () => {
    await renderCatalog();
    const card = (await screen.findAllByTestId('catalog-card'))[0];
    openMenu(within(card).getByTestId(`catalog-card-menu-${LEDGER.id}`));
    fireEvent.click(await screen.findByText('Delete item'));
    await waitFor(() => expect(mockDeleteProject).toHaveBeenCalledWith(LEDGER.id));
    expect(mockConfirm).toHaveBeenCalledWith(
      expect.objectContaining({
        title: 'Delete catalog item "Ledger Graph"?',
        typeToConfirm: undefined,
      })
    );
  });

  it('gates a permanent delete once, on the slug', async () => {
    await renderCatalog();
    const card = (await screen.findAllByTestId('catalog-card'))[0];
    openMenu(within(card).getByTestId(`catalog-card-menu-${LEDGER.id}`));
    fireEvent.click(await screen.findByText('Permanently delete'));
    await waitFor(() => expect(mockPermanentDelete).toHaveBeenCalledWith(LEDGER.id));
    // One confirm, not the two identical native ones the screen this replaces asked for.
    expect(mockConfirm).toHaveBeenCalledTimes(1);
    expect(mockConfirm).toHaveBeenCalledWith(
      expect.objectContaining({ typeToConfirm: 'ledger-graph' })
    );
  });

  it('undeletes from the deleted card’s own footer', async () => {
    await renderCatalog();
    fireEvent.click(screen.getByLabelText('Show soft-deleted catalog items in the list'));
    await screen.findByText('Legacy Graph');
    const recovery = screen.getByTestId('catalog-card-recovery');
    fireEvent.click(within(recovery).getByRole('button', { name: 'Undelete' }));
    await waitFor(() => expect(mockRestoreProject).toHaveBeenCalledWith(RETIRED.id));
  });

  it('acts on a selection in bulk, from the table', async () => {
    await renderCatalog();
    await screen.findByText('Ledger Graph');
    await showTable();
    const table = screen.getByTestId('catalog-table');
    const boxes = within(table).getAllByRole('checkbox');
    // The first is select-all; the next two are rows.
    fireEvent.click(boxes[1]);
    fireEvent.click(boxes[2]);
    fireEvent.click(await screen.findByTestId('catalog-bulk-delete'));
    await waitFor(() => expect(mockDeleteProject).toHaveBeenCalledTimes(2));
  });
});

// ---------------------------------------------------------------------------------------
// Overlays and states
// ---------------------------------------------------------------------------------------

describe('overlays', () => {
  it('opens the 6.4 import wizard from the header', async () => {
    await renderCatalog();
    fireEvent.click(await screen.findByTestId('catalog-import'));
    expect(await screen.findByTestId('catalog-import-dialog')).toBeInTheDocument();
  });

  it('opens it from the empty state too', async () => {
    await renderCatalog([]);
    fireEvent.click(await screen.findByTestId('catalog-empty-import'));
    expect(await screen.findByTestId('catalog-import-dialog')).toBeInTheDocument();
  });

  it('opens the conversion preview from the row menu', async () => {
    await renderCatalog();
    const card = (await screen.findAllByTestId('catalog-card'))[0];
    openMenu(within(card).getByTestId(`catalog-card-menu-${LEDGER.id}`));
    fireEvent.click(await screen.findByTestId('catalog-action-convert'));
    expect(await screen.findByTestId('catalog-convert-dialog')).toBeInTheDocument();
  });

  it('opens the server lint report from the card’s Lint orb', async () => {
    await renderCatalog();
    const card = (await screen.findAllByTestId('catalog-card'))[0];
    fireEvent.click(within(card).getByRole('button', { name: /Lint/ }));
    expect(await screen.findByTestId('catalog-lint-dialog')).toBeInTheDocument();
  });

  it('sends a scored item’s Quality orb to the server report, not to local history', async () => {
    // `catalogQualityOpensServerLintReport`: a numeric server score means the report exists.
    await renderCatalog();
    const card = (await screen.findAllByTestId('catalog-card'))[0];
    fireEvent.click(within(card).getByRole('button', { name: /Quality/ }));
    expect(await screen.findByTestId('catalog-lint-dialog')).toBeInTheDocument();
  });
});

describe('states', () => {
  it('holds the cards view with card-shaped skeletons while the first read is in flight', async () => {
    // A read that never settles: the screen stays in its loading state.
    global.fetch = jest.fn(() => new Promise(() => undefined)) as unknown as typeof fetch;
    render(<CatalogClient />);
    const region = await screen.findByTestId('catalog-cards-loading');
    expect(region).toHaveAttribute('role', 'status');
    expect(region).toHaveTextContent('Loading catalog…');
    expect(within(region).getAllByTestId('catalog-card-skeleton')).toHaveLength(3);
    // The toolbar is already in place above them, so nothing moves when the cards land.
    expect(screen.getByTestId('catalog-toolbar')).toBeInTheDocument();
  });

  it('holds the table with per-column skeleton rows while the first read is in flight', async () => {
    window.localStorage.setItem(CATALOG_VIEW_PREFS_STORAGE_KEY, JSON.stringify({ viewMode: 'table' }));
    global.fetch = jest.fn(() => new Promise(() => undefined)) as unknown as typeof fetch;
    render(<CatalogClient />);
    const table = await screen.findByTestId('catalog-table');
    await waitFor(() =>
      expect(table.querySelector('tbody[aria-busy="true"], [aria-busy="true"]')).not.toBeNull()
    );
    expect(table.querySelectorAll('tbody tr[aria-hidden] .hive-skeleton').length).toBeGreaterThan(0);
  });

  it('says a failed read failed, instead of showing an empty catalog', async () => {
    await renderCatalog(ALL_ROWS, { fail: true });
    expect(await screen.findByText('The catalog could not be loaded')).toBeInTheDocument();
    expect(screen.queryByText('Your catalog is empty')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument();
  });

  it('explains what the catalog is when it is empty, and points OpenAPI at Projects', async () => {
    await renderCatalog([]);
    const empty = await screen.findByText('Your catalog is empty');
    expect(empty.parentElement?.textContent).toContain('OpenAPI-worthy non-OpenAPI imports');
    // Two links say the same thing on an empty catalog — the always-on note and the empty
    // state — and both have to point at Projects.
    for (const link of screen.getAllByRole('link', { name: 'Projects' })) {
      expect(link).toHaveAttribute('href', '/ade/dashboard/projects');
    }
  });
});

// ---------------------------------------------------------------------------------------
// Bulk actions (MFI-28.5)
// ---------------------------------------------------------------------------------------

describe('bulk actions (MFI-28.5)', () => {
  it('puts a checkbox on every card, and a select-all over the cards view', async () => {
    await renderCatalog();
    const cards = await screen.findAllByTestId('catalog-card');
    expect(within(cards[0]).getByRole('checkbox', { name: /^Select / })).toBeInTheDocument();
    expect(screen.queryByTestId('catalog-cards-bulk-bar')).not.toBeInTheDocument();

    fireEvent.click(within(cards[0]).getByRole('checkbox', { name: /^Select / }));
    const bar = await screen.findByTestId('catalog-cards-bulk-bar');
    expect(bar).toHaveTextContent('1 catalog item selected');
    expect(cards[0]).toHaveAttribute('data-selected', 'true');

    fireEvent.click(screen.getByRole('checkbox', { name: /^Select all \d+/ }));
    expect(bar).toHaveTextContent(`${cards.length} catalog items selected`);
    fireEvent.click(screen.getByRole('checkbox', { name: 'Clear selection' }));
    expect(screen.queryByTestId('catalog-cards-bulk-bar')).not.toBeInTheDocument();
  });

  it('keeps a card selection when the view switches to the table', async () => {
    await renderCatalog();
    const card = (await screen.findAllByTestId('catalog-card'))[0];
    fireEvent.click(within(card).getByRole('checkbox', { name: /^Select / }));
    await showTable();
    expect(screen.getByText('1 catalog item selected')).toBeInTheDocument();
  });

  it('exposes bulk delete and bulk convert for the selected cards', async () => {
    await renderCatalog();
    const cards = await screen.findAllByTestId('catalog-card');
    fireEvent.click(within(cards[0]).getByRole('checkbox', { name: /^Select / }));
    fireEvent.click(within(cards[1]).getByRole('checkbox', { name: /^Select / }));
    const bar = await screen.findByTestId('catalog-cards-bulk-bar');
    expect(within(bar).getByTestId('catalog-bulk-delete')).toHaveTextContent('Delete 2');
    expect(within(bar).getByTestId('catalog-bulk-convert')).toHaveTextContent('Convert 2…');
  });

  it('opens the bulk convert review on the selected items', async () => {
    await renderCatalog();
    await screen.findByText('Ledger Graph');
    await showTable();
    const boxes = within(screen.getByTestId('catalog-table')).getAllByRole('checkbox');
    fireEvent.click(boxes[1]);
    fireEvent.click(boxes[2]);
    fireEvent.click(await screen.findByTestId('catalog-bulk-convert'));
    const dialog = await screen.findByTestId('catalog-bulk-convert-dialog');
    expect(dialog).toHaveTextContent('Convert 2 catalog items to OpenAPI');
    expect(within(dialog).getAllByRole('listitem')).toHaveLength(2);
  });

  it('offers no Convert for a selection of deleted items only', async () => {
    await renderCatalog();
    fireEvent.click(screen.getByLabelText('Show soft-deleted catalog items in the list'));
    const deletedCard = (await screen.findAllByTestId('catalog-card')).find(
      (card) => card.getAttribute('data-catalog-id') === RETIRED.id
    ) as HTMLElement;
    fireEvent.click(within(deletedCard).getByRole('checkbox', { name: /^Select / }));
    const bar = await screen.findByTestId('catalog-cards-bulk-bar');
    expect(within(bar).getByTestId('catalog-bulk-restore')).toHaveTextContent('Undelete 1');
    expect(within(bar).queryByTestId('catalog-bulk-convert')).not.toBeInTheDocument();
  });

  it('reports a partial bulk delete per item, naming each refusal', async () => {
    mockDeleteProject
      .mockImplementationOnce(async () => JSON.stringify({ success: true }))
      .mockImplementationOnce(async () => JSON.stringify({ success: false, error: 'Item is locked' }));
    await renderCatalog();
    const cards = await screen.findAllByTestId('catalog-card');
    fireEvent.click(within(cards[0]).getByRole('checkbox', { name: /^Select / }));
    fireEvent.click(within(cards[1]).getByRole('checkbox', { name: /^Select / }));
    fireEvent.click(await screen.findByTestId('catalog-bulk-delete'));
    await waitFor(() => expect(mockAlert).toHaveBeenCalledTimes(1));
    const options = mockAlert.mock.calls[0][0] as { title: string; message: React.ReactElement };
    expect(options.title).toBe('1 catalog item could not be deleted');
    render(options.message);
    const list = screen.getByTestId('catalog-bulk-failures');
    expect(within(list).getAllByRole('listitem')).toHaveLength(1);
    expect(list).toHaveTextContent('Item is locked');
  });
});

// ---------------------------------------------------------------------------------------
// Keyboard and axe (MFI-28.8)
// ---------------------------------------------------------------------------------------

/** jsdom cannot compute colour, and the region rule wants the app shell this screen sits in. */
const AXE_OPTIONS = {
  rules: { 'color-contrast': { enabled: false }, region: { enabled: false } },
} as const;

describe('keyboard (MFI-28.8)', () => {
  it('wraps the actions menu’s arrow keys at either end', async () => {
    await renderCatalog();
    const card = (await screen.findAllByTestId('catalog-card'))[0];
    openMenu(within(card).getByTestId(`catalog-card-menu-${LEDGER.id}`));
    const items = await screen.findAllByRole('menuitem');
    // Radix focuses the first item on a keyboard open; ArrowUp then wraps to the last.
    await waitFor(() => expect(items[0]).toHaveFocus());
    fireEvent.keyDown(items[0], { key: 'ArrowUp' });
    await waitFor(() => expect(items[items.length - 1]).toHaveFocus());
    fireEvent.keyDown(items[items.length - 1], { key: 'ArrowDown' });
    await waitFor(() => expect(items[0]).toHaveFocus());
  });

  it('closes the actions menu on Escape and puts focus back on its trigger', async () => {
    await renderCatalog();
    const card = (await screen.findAllByTestId('catalog-card'))[0];
    const trigger = within(card).getByTestId(`catalog-card-menu-${LEDGER.id}`);
    openMenu(trigger);
    const first = (await screen.findAllByRole('menuitem'))[0];
    fireEvent.keyDown(first, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByRole('menu')).not.toBeInTheDocument());
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  it('runs a verb only after focus is back on the trigger, so its dialog can return there', async () => {
    await renderCatalog();
    const card = (await screen.findAllByTestId('catalog-card'))[0];
    const trigger = within(card).getByTestId(`catalog-card-menu-${LEDGER.id}`);
    openMenu(trigger);
    fireEvent.click(await screen.findByTestId('catalog-action-convert'));
    expect(await screen.findByTestId('catalog-convert-dialog')).toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it('wraps the sort menu too', async () => {
    await renderCatalog();
    await screen.findAllByTestId('catalog-card');
    openMenu(screen.getByTestId('catalog-sort-menu'));
    const items = await screen.findAllByRole('menuitem');
    await waitFor(() => expect(items[0]).toHaveFocus());
    fireEvent.keyDown(items[0], { key: 'ArrowUp' });
    await waitFor(() => expect(items[items.length - 1]).toHaveFocus());
  });

  it('puts every card control in the tab order and leaves nothing clickable that is not', async () => {
    await renderCatalog();
    const card = (await screen.findAllByTestId('catalog-card'))[0];
    // One link, the scored orbs, and the menu trigger — each a native, focusable control.
    expect(within(card).getByRole('link', { name: LEDGER.name })).toBeInTheDocument();
    expect(within(card).getByRole('button', { name: /Quality/ })).toBeInTheDocument();
    expect(within(card).getByRole('button', { name: /Lint/ })).toBeInTheDocument();
    expect(within(card).getByRole('button', { name: `Actions for ${LEDGER.name}` })).toBeInTheDocument();
    for (const el of Array.from(card.querySelectorAll<HTMLElement>('[tabindex]'))) {
      expect(el.tabIndex).toBeGreaterThanOrEqual(0);
    }
  });
});

describe('axe (MFI-28.8)', () => {
  it('passes on the cards view', async () => {
    await renderCatalog();
    await screen.findAllByTestId('catalog-card');
    expect(await axe(document.body, AXE_OPTIONS)).toHaveNoViolations();
  });

  it('passes on the table view', async () => {
    await renderCatalog();
    await screen.findByText('Ledger Graph');
    await showTable();
    expect(await axe(document.body, AXE_OPTIONS)).toHaveNoViolations();
  });

  it('passes with the actions menu open', async () => {
    await renderCatalog();
    const card = (await screen.findAllByTestId('catalog-card'))[0];
    openMenu(within(card).getByTestId(`catalog-card-menu-${LEDGER.id}`));
    await screen.findAllByRole('menuitem');
    expect(await axe(document.body, AXE_OPTIONS)).toHaveNoViolations();
  });
});

/**
 * `e2e/hive-catalog.spec.ts` measures this screen in a real browser — no horizontal document
 * scroll across the nine themes, both densities and all six font scales, and axe — against
 * markup the components actually render. That markup is written here, from the very renders
 * this suite pins, into `e2e/fixtures/hive-catalog/` when `CATALOG_FIXTURE_DUMP=1` is set:
 *
 *     CATALOG_FIXTURE_DUMP=1 npx jest -c jest.config.ts \
 *       tests/catalog-hive-redesign.test.tsx -t fixtures
 *
 * Without the variable the test still runs — it renders every surface and checks each is there
 * — so a change to a component that would leave the fixtures stale fails loudly here before it
 * fails quietly in the browser.
 */
describe('the browser fixtures', () => {
  const OUT = path.join(__dirname, '..', 'e2e', 'fixtures', 'hive-catalog');
  const dump = process.env.CATALOG_FIXTURE_DUMP === '1';

  /** Write one fixture, or just assert it could be. */
  const write = (name: string, html: string) => {
    expect(html.length).toBeGreaterThan(0);
    if (!dump) return;
    fs.mkdirSync(OUT, { recursive: true });
    fs.writeFileSync(path.join(OUT, `${name}.html`), html);
  };

  /** The page column the shell would put this screen in. */
  const page = () => document.querySelector('.page') as HTMLElement;

  it('renders every surface the browser spec mounts (and writes the fixtures on request)', async () => {
    await renderCatalog();
    await screen.findByText('Ledger Graph');

    // Cards, grouped — the state a reader lands on.
    write('cards', page().outerHTML);

    // The same cards in one flat grid. The browser spec measures column collapse here rather
    // than on the grouped fixture: `auto-fit` collapses a track with nothing in it, so a
    // paradigm section holding one card reports one column at every width.
    fireEvent.click(screen.getByTestId('catalog-group-none'));
    await waitFor(() => expect(screen.getAllByTestId('catalog-card')).toHaveLength(3));
    write('flat', page().outerHTML);
    fireEvent.click(screen.getByTestId('catalog-group-protocol'));

    // "How the catalog works" open over the page. Radix portals the dialog (and its scrim)
    // out of `.page`, so the portal is written after the page, as the browser would stack it.
    fireEvent.click(screen.getByRole('button', { name: 'How the catalog works' }));
    const about = await screen.findByRole('dialog', { name: 'How the catalog works' });
    await waitFor(() =>
      expect(within(about).getByTestId('catalog-about-counts')).toHaveTextContent(/unavailable/)
    );
    write('about', page().outerHTML + (about.parentElement as HTMLElement).outerHTML);
    fireEvent.click(within(about).getByRole('button', { name: 'Got it' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());

    // A returning reader: the first-visit explainer dismissed. Everything below — the deleted
    // view and the table the parity harness and the docs screenshot measure — is that page.
    fireEvent.click(within(screen.getByRole('note')).getByRole('button', { name: 'Got it' }));

    // The deleted card's amber treatment and its two recovery verbs.
    fireEvent.click(screen.getByLabelText('Show soft-deleted catalog items in the list'));
    await screen.findByText('Legacy Graph');
    write('deleted', page().outerHTML);

    // The table, which is the only surface that can scroll sideways.
    await showTable();
    write('table', page().outerHTML);
  });

  it('writes the bulk selection and the bulk convert review (MFI-28.5)', async () => {
    await renderCatalog();
    await screen.findByText('Ledger Graph');
    // Serve the review's dry-runs on top of the list's own reads: one clean, two low-tier —
    // so the review shows the per-item acknowledgements *and* the apply-to-all gate.
    const listFetch = global.fetch;
    global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (!url.includes('/convert')) return (listFetch as typeof fetch)(input, init);
      const low = url.includes(ORDERS.id) || url.includes(EVENTS.id);
      return {
        ok: true,
        status: 200,
        json: async () => ({
          success: true,
          report: {
            score: low ? 34 : 92,
            grade: low ? 'F' : 'A',
            tier: low ? 'low' : 'high',
            items: [],
            losses: [],
            coverage_counts: {},
            penalty: 0,
          },
        }),
      };
    }) as unknown as typeof fetch;

    fireEvent.click(within(screen.getByRole('note')).getByRole('button', { name: 'Got it' }));
    for (const name of ['Ledger Graph', 'Orders RPC', 'Events Bus']) {
      fireEvent.click(screen.getByRole('checkbox', { name: `Select ${name}` }));
    }
    await screen.findByTestId('catalog-cards-bulk-bar');
    write('bulk-selection', page().outerHTML);

    fireEvent.click(screen.getByTestId('catalog-bulk-convert'));
    const dialog = await screen.findByTestId('catalog-bulk-convert-dialog');
    await waitFor(() => expect(within(dialog).queryAllByText('Previewing…')).toHaveLength(0));
    write('bulk-convert', page().outerHTML + (dialog.parentElement as HTMLElement).outerHTML);
  });

  it('writes the empty state', async () => {
    await renderCatalog([]);
    await screen.findByText('Your catalog is empty');
    write('empty', page().outerHTML);
  });
});
