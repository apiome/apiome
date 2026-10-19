/**
 * URL-synced detail tabs & the keyboard pass (MFI-28.8, #4124).
 *
 * Three things are pinned here:
 *
 *  1. `catalogDetailTabSearch` — the one rule that turns "this pane is open" into a query
 *     string: Overview is the bare route, other panes are `?tab=<id>`, unrelated parameters
 *     survive, and the pane-scoped ones (`sourcePath`/`line`, `node`) go when their pane does.
 *  2. The detail shell writes that query with `history.replaceState` on every pane switch —
 *     click, arrow key, or a cross-pane link — and still honours a deep link on load.
 *  3. Focus return: a verb picked from the shared row menu opens its dialog only once the menu
 *     has given focus back to its trigger, so a dialog built on `useReturnFocus` hands focus
 *     back to that trigger when it closes rather than dropping it on `<body>`.
 */

import React from 'react';
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { axe } from 'jest-axe';
import 'jest-axe/extend-expect';

const mockPush = jest.fn();
let mockSearch = '';
jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush }),
  useSearchParams: () => new URLSearchParams(mockSearch),
}));

jest.mock('@lib/auth/session-client', () => ({
  useAuthSession: () => ({ data: { user: { current_tenant_id: 'tenant-1' } } }),
}));

jest.mock('@monaco-editor/react', () => ({
  __esModule: true,
  default: (props: { value?: string }) => <textarea readOnly value={props.value ?? ''} />,
}));

import { CatalogItemDetailClient } from '../src/app/ade/dashboard/catalog/[id]/CatalogItemDetailClient';
import { catalogDetailTabSearch } from '../src/app/components/ade/catalog/detail';
import { CatalogRowMenu } from '../src/app/components/ade/catalog/CatalogCard';
import type { CatalogItem } from '../src/app/components/ade/catalog/catalogModel';
import { Dialog, DialogContent, DialogTitle } from '../src/app/components/ui/Dialog';
import { useReturnFocus } from '../src/app/components/dialogs/useReturnFocus';

/** jsdom cannot compute colour, and the region rule wants the app shell this screen sits in. */
const AXE_OPTIONS = {
  rules: { 'color-contrast': { enabled: false }, region: { enabled: false } },
} as const;

const ITEM = {
  id: '11111111-2222-3333-4444-555555555555',
  name: 'Acme gRPC API',
  slug: 'acme-grpc-api',
  description: 'Imported from a .proto file.',
  enabled: true,
  deleted_at: null,
  created_at: '2026-06-01T00:00:00.000Z',
  updated_at: '2026-06-20T12:00:00.000Z',
  creator_name: 'Dana Import',
  creator_email: 'dana@example.com',
  qualityScore: 82,
  qualityGrade: 'B',
  publishable: false,
  sourceFormat: 'protobuf',
  protocol: 'grpc',
  formatMetadata: { sourceLabel: 'acme.proto', inputKind: 'file' },
  summary: { services: 2, operations: 7, types: 12, channels: 0 },
  source: { kind: 'file', label: 'acme.proto', uri: null, hasContent: true, downloadable: true },
};

const DETAIL_PATH = `/ade/dashboard/catalog/${ITEM.id}`;

/** Serve the detail read; every lazy pane read is a 404, so each pane draws its own empty state. */
function mockFetchItem() {
  global.fetch = jest.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url === `/api/catalog/${encodeURIComponent(ITEM.id)}`) {
      return { ok: true, json: async () => ({ success: true, item: ITEM }) };
    }
    return {
      ok: false,
      status: 404,
      json: async () => ({ success: false, error: 'Not found' }),
      text: async () => '',
    };
  }) as unknown as typeof fetch;
}

/** Point jsdom's address bar at the detail route with `search`, as a deep link would. */
function setAddress(search = '') {
  mockSearch = search.replace(/^\?/, '');
  window.history.replaceState(null, '', `${DETAIL_PATH}${search}`);
}

async function renderDetail(search = '') {
  setAddress(search);
  mockFetchItem();
  render(<CatalogItemDetailClient itemId={ITEM.id} />);
  await screen.findByTestId('catalog-detail-tabs');
}

afterEach(() => {
  jest.restoreAllMocks();
  mockPush.mockReset();
  setAddress('');
});

// ---------------------------------------------------------------------------------------
// The rule
// ---------------------------------------------------------------------------------------

describe('catalogDetailTabSearch', () => {
  it('spells Overview as the bare route', () => {
    expect(catalogDetailTabSearch('?tab=lint', 'overview')).toBe('');
    expect(catalogDetailTabSearch('', 'overview')).toBe('');
  });

  it('names any other pane with ?tab=', () => {
    expect(catalogDetailTabSearch('', 'lint')).toBe('?tab=lint');
    expect(catalogDetailTabSearch('?tab=lint', 'test-bench')).toBe('?tab=test-bench');
  });

  it('keeps parameters that are not about a pane', () => {
    expect(catalogDetailTabSearch('?identityGroupId=g1', 'versions')).toBe(
      '?identityGroupId=g1&tab=versions'
    );
    expect(catalogDetailTabSearch('identityGroupId=g1&tab=lint', 'overview')).toBe(
      '?identityGroupId=g1'
    );
  });

  it('drops the source pair when the reader leaves Source & code, since it would win over ?tab=', () => {
    expect(catalogDetailTabSearch('?tab=source&sourcePath=a.proto&line=4', 'lint')).toBe('?tab=lint');
    expect(catalogDetailTabSearch('?tab=source&sourcePath=a.proto&line=4', 'source')).toBe(
      '?tab=source&sourcePath=a.proto&line=4'
    );
  });

  it('drops ?node= when the reader leaves Format details', () => {
    expect(catalogDetailTabSearch('?tab=format&node=n1', 'provenance')).toBe('?tab=provenance');
    expect(catalogDetailTabSearch('?tab=format&node=n1', 'format')).toBe('?tab=format&node=n1');
  });
});

// ---------------------------------------------------------------------------------------
// The shell
// ---------------------------------------------------------------------------------------

describe('URL-synced detail tabs', () => {
  it('opens Overview by default and leaves the address bare', async () => {
    await renderDetail();
    expect(screen.getByTestId('catalog-detail-tab-overview')).toHaveAttribute('aria-selected', 'true');
    expect(window.location.search).toBe('');
  });

  it.each(['lint', 'versions', 'provenance', 'test-bench'])('opens ?tab=%s on load', async (tab) => {
    await renderDetail(`?tab=${tab}`);
    await waitFor(() =>
      expect(screen.getByTestId(`catalog-detail-tab-${tab}`)).toHaveAttribute('aria-selected', 'true')
    );
    expect(screen.getByTestId(`catalog-detail-pane-${tab}`)).not.toHaveAttribute('hidden');
  });

  it('falls back to Overview for an unknown ?tab=', async () => {
    await renderDetail('?tab=nope');
    expect(screen.getByTestId('catalog-detail-tab-overview')).toHaveAttribute('aria-selected', 'true');
  });

  it('records a clicked tab in the address without navigating', async () => {
    const replace = jest.spyOn(window.history, 'replaceState');
    await renderDetail();
    fireEvent.click(screen.getByTestId('catalog-detail-tab-lint'));
    expect(window.location.pathname).toBe(DETAIL_PATH);
    expect(window.location.search).toBe('?tab=lint');
    expect(replace).toHaveBeenCalled();
    expect(mockPush).not.toHaveBeenCalled();

    fireEvent.click(screen.getByTestId('catalog-detail-tab-overview'));
    expect(window.location.search).toBe('');
  });

  it('records a tab reached with the arrow keys', async () => {
    await renderDetail();
    const overview = screen.getByTestId('catalog-detail-tab-overview');
    fireEvent.keyDown(overview, { key: 'ArrowRight' });
    expect(screen.getByTestId('catalog-detail-tab-format')).toHaveFocus();
    expect(window.location.search).toBe('?tab=format');
    fireEvent.keyDown(screen.getByTestId('catalog-detail-tab-format'), { key: 'End' });
    // The item is Protobuf, so its last pane is Subjects (CDG-4.5).
    expect(window.location.search).toBe('?tab=subjects');
  });

  it('records the pane "View code" opens', async () => {
    await renderDetail();
    fireEvent.click(screen.getByTestId('catalog-detail-view-code'));
    expect(window.location.search).toBe('?tab=source');
  });

  it('does not add a history entry per tab', async () => {
    const push = jest.spyOn(window.history, 'pushState');
    await renderDetail();
    fireEvent.click(screen.getByTestId('catalog-detail-tab-lint'));
    fireEvent.click(screen.getByTestId('catalog-detail-tab-versions'));
    expect(push).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------------------
// Focus return
// ---------------------------------------------------------------------------------------

const ROW = {
  id: 'row-1',
  name: 'Ledger Graph',
  slug: 'ledger-graph',
  enabled: true,
  deleted_at: null,
  sourceFormat: 'graphql',
  conversion: null,
} as unknown as CatalogItem;

/** A row menu whose Convert opens a real Hive dialog wired the way the catalog's dialogs are. */
function MenuWithDialog() {
  const [open, setOpen] = React.useState(false);
  const returnFocus = useReturnFocus(open);
  const noop = () => undefined;
  return (
    <>
      <CatalogRowMenu
        item={ROW}
        testId="row-menu"
        onOpenDetail={noop}
        onOpenVersions={noop}
        onOpenLint={noop}
        onExport={noop}
        onConvert={() => setOpen(true)}
        onDelete={noop}
        onRestore={noop}
        onPermanentDelete={noop}
      />
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent onCloseAutoFocus={returnFocus} aria-describedby={undefined}>
          <DialogTitle>Convert</DialogTitle>
        </DialogContent>
      </Dialog>
    </>
  );
}

describe('focus return (MFI-28.8)', () => {
  it('lands back on the menu trigger when a dialog opened from the menu closes', async () => {
    render(<MenuWithDialog />);
    const trigger = screen.getByTestId('row-menu');
    trigger.focus();
    fireEvent.keyDown(trigger, { key: 'Enter' });
    fireEvent.click(await screen.findByTestId('catalog-action-convert'));

    const dialog = await screen.findByRole('dialog');
    await waitFor(() => expect(dialog.contains(document.activeElement)).toBe(true));
    fireEvent.keyDown(document.activeElement as HTMLElement, { key: 'Escape' });

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  it('lands back on the detail header button that opened the lint report', async () => {
    await renderDetail();
    const orb = screen.getByTestId('catalog-detail-lint-orb');
    orb.focus();
    fireEvent.click(orb);
    const dialog = await screen.findByRole('dialog');
    await waitFor(() => expect(dialog.contains(document.activeElement)).toBe(true));
    fireEvent.keyDown(document.activeElement as HTMLElement, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    await waitFor(() => expect(orb).toHaveFocus());
  });
});

// ---------------------------------------------------------------------------------------
// axe
// ---------------------------------------------------------------------------------------

describe('axe (MFI-28.8)', () => {
  it.each(['overview', 'provenance', 'lint', 'versions'])('passes on the %s pane', async (tab) => {
    await renderDetail(tab === 'overview' ? '' : `?tab=${tab}`);
    await waitFor(() =>
      expect(screen.getByTestId(`catalog-detail-tab-${tab}`)).toHaveAttribute('aria-selected', 'true')
    );
    const tabs = screen.getByTestId('catalog-detail-tabs');
    expect(within(tabs).getAllByRole('tab')).toHaveLength(10); // nine panes + Subjects (a Protobuf item)
    expect(await axe(document.body, AXE_OPTIONS)).toHaveNoViolations();
  });
});
