/**
 * Render/interaction tests for the inline versions timeline + diff (MFI-25.7 #4092, MFI-28.1 #4117).
 *
 * The Versions tab must fetch the shared `/api/versions` list, render it newest-first with a checkbox
 * per revision, and — once exactly two are ticked — render their diff **in-place** (no route change)
 * via the shared Monaco diff viewer. The layout toggle (side-by-side/unified) is persisted in
 * localStorage, an expand-all/collapse-all control folds/reveals the unchanged regions, and the
 * off-page "Open version history" link is retained as the escape hatch. These assertions pin that
 * contract plus the loading / error / empty degradations.
 */

import React from 'react';
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react';
import '@testing-library/jest-dom';

const mockPush = jest.fn();
jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush }),
}));

// The compare read reuses the versions-dashboard server action (DB-backed) — mock it so the panel is
// testable under jsdom, and so we can assert it is called with the ordered (old → new) pair.
const mockLoadSpec = jest.fn();
jest.mock('../src/app/utils/catalog-revision-diff', () => ({
  loadCatalogRevisionSpec: (...args: unknown[]) => mockLoadSpec(...args),
}));

// Stub the Monaco diff viewer (dynamic monaco import never resolves under jsdom); expose its key props
// so the layout toggle and expand-all wiring can be asserted.
jest.mock('../src/app/components/ui/code/JsonDiffViewer', () => ({
  JsonDiffViewer: (props: {
    original: string;
    modified: string;
    mode: string;
    hideUnchangedRegions?: boolean;
  }) => (
    <div
      data-testid="mock-diff-viewer"
      data-mode={props.mode}
      data-hide-unchanged={String(props.hideUnchangedRegions)}
      data-original={props.original}
      data-modified={props.modified}
    />
  ),
}));

import { CatalogVersionsPanel } from '../src/app/components/ade/dashboard/catalog/CatalogVersionsPanel';

const ITEM_ID = '11111111-2222-3333-4444-555555555555';

const VERSIONS = [
  {
    id: 'rev-old',
    version_id: '1.0.0',
    created_at: '2026-01-01T00:00:00.000Z',
    shortMessage: 'Initial import',
    published: true,
    creator_name: 'Dana Import',
  },
  {
    id: 'rev-mid',
    version_id: '1.1.0',
    created_at: '2026-02-01T00:00:00.000Z',
    shortMessage: 'Add pagination',
    lifecycle: 'beta',
  },
  {
    id: 'rev-new',
    version_id: '1.2.0',
    created_at: '2026-03-01T00:00:00.000Z',
    shortMessage: 'Deprecate v1 fields',
  },
];

function mockVersionsFetch(versions: unknown, ok = true) {
  global.fetch = jest.fn().mockResolvedValue({
    ok,
    status: ok ? 200 : 500,
    json: async () => (ok ? { success: true, versions } : { success: false, error: 'boom' }),
  }) as unknown as typeof fetch;
}

/** Resolve each revision's spec to a deterministic, revision-tagged JSON string. */
function stubSpecsByRevisionId() {
  mockLoadSpec.mockImplementation((revision: { id: string }) =>
    Promise.resolve(`{"revision":"${revision.id}"}`),
  );
}

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(() => {
  jest.clearAllMocks();
});

describe('CatalogVersionsPanel', () => {
  it('does not fetch until the tab is active (lazy)', async () => {
    mockVersionsFetch(VERSIONS);
    render(<CatalogVersionsPanel itemId={ITEM_ID} active={false} />);
    expect(global.fetch).not.toHaveBeenCalled();
    expect(screen.getByTestId('catalog-versions-loading')).toBeInTheDocument();
  });

  it('renders revisions newest-first once active', async () => {
    mockVersionsFetch(VERSIONS);
    render(<CatalogVersionsPanel itemId={ITEM_ID} active />);

    await screen.findByTestId('catalog-versions-timeline');
    expect(global.fetch).toHaveBeenCalledWith(
      `/api/versions?projectId=${encodeURIComponent(ITEM_ID)}`,
      expect.objectContaining({ method: 'GET' }),
    );
    const rows = screen.getAllByTestId('catalog-versions-row');
    expect(rows.map((r) => r.getAttribute('data-revision-id'))).toEqual([
      'rev-new',
      'rev-mid',
      'rev-old',
    ]);
    // Published + lifecycle chips render.
    expect(within(rows[2]).getByText(/Published/i)).toBeInTheDocument();
    expect(within(rows[1]).getByText('beta')).toBeInTheDocument();
  });

  it('renders the diff inline (no route change) once exactly two revisions are ticked', async () => {
    mockVersionsFetch(VERSIONS);
    stubSpecsByRevisionId();
    render(<CatalogVersionsPanel itemId={ITEM_ID} itemName="Catalog Item" active />);

    await screen.findByTestId('catalog-versions-timeline');
    // No diff before a full pair is selected.
    expect(screen.queryByTestId('catalog-versions-diff')).not.toBeInTheDocument();

    const checkboxes = screen.getAllByTestId('catalog-versions-checkbox');
    // Order is newest-first: [rev-new, rev-mid, rev-old].
    fireEvent.click(checkboxes[0]); // rev-new
    expect(screen.queryByTestId('catalog-versions-diff')).not.toBeInTheDocument();
    fireEvent.click(checkboxes[2]); // rev-old

    const viewer = await screen.findByTestId('mock-diff-viewer');
    // Older (rev-old) → original/base, newer (rev-new) → modified/head, regardless of tick order.
    expect(viewer).toHaveAttribute('data-original', '{"revision":"rev-old"}');
    expect(viewer).toHaveAttribute('data-modified', '{"revision":"rev-new"}');
    // The compare read is invoked per revision with (revision, itemId, itemName, itemMetadata).
    expect(mockLoadSpec).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'rev-old' }),
      ITEM_ID,
      'Catalog Item',
      undefined,
    );
    // Inline only — the reader is never routed away.
    expect(mockPush).not.toHaveBeenCalled();
  });

  it('persists the side-by-side/unified layout toggle across mounts', async () => {
    mockVersionsFetch(VERSIONS);
    stubSpecsByRevisionId();
    const { unmount } = render(<CatalogVersionsPanel itemId={ITEM_ID} active />);

    await screen.findByTestId('catalog-versions-timeline');
    const checkboxes = screen.getAllByTestId('catalog-versions-checkbox');
    fireEvent.click(checkboxes[0]);
    fireEvent.click(checkboxes[1]);

    let viewer = await screen.findByTestId('mock-diff-viewer');
    expect(viewer).toHaveAttribute('data-mode', 'split');

    fireEvent.click(screen.getByTestId('catalog-versions-diff-mode-unified'));
    expect(await screen.findByTestId('mock-diff-viewer')).toHaveAttribute('data-mode', 'unified');
    expect(window.localStorage.getItem('catalog-versions-diff-mode')).toBe('unified');

    // A fresh mount reads the remembered layout.
    unmount();
    render(<CatalogVersionsPanel itemId={ITEM_ID} active />);
    await screen.findByTestId('catalog-versions-timeline');
    fireEvent.click(screen.getAllByTestId('catalog-versions-checkbox')[0]);
    fireEvent.click(screen.getAllByTestId('catalog-versions-checkbox')[1]);
    viewer = await screen.findByTestId('mock-diff-viewer');
    expect(viewer).toHaveAttribute('data-mode', 'unified');
  });

  it('expand-all/collapse-all governs the unchanged regions', async () => {
    mockVersionsFetch(VERSIONS);
    stubSpecsByRevisionId();
    render(<CatalogVersionsPanel itemId={ITEM_ID} active />);

    await screen.findByTestId('catalog-versions-timeline');
    fireEvent.click(screen.getAllByTestId('catalog-versions-checkbox')[0]);
    fireEvent.click(screen.getAllByTestId('catalog-versions-checkbox')[1]);

    // Default (collapsed): unchanged regions are hidden.
    let viewer = await screen.findByTestId('mock-diff-viewer');
    expect(viewer).toHaveAttribute('data-hide-unchanged', 'true');

    // Expand all reveals them.
    fireEvent.click(screen.getByTestId('catalog-versions-expand-all'));
    viewer = await screen.findByTestId('mock-diff-viewer');
    expect(viewer).toHaveAttribute('data-hide-unchanged', 'false');
  });

  it('caps selection at two by disabling the remaining checkboxes', async () => {
    mockVersionsFetch(VERSIONS);
    stubSpecsByRevisionId();
    render(<CatalogVersionsPanel itemId={ITEM_ID} active />);

    await screen.findByTestId('catalog-versions-timeline');
    const checkboxes = screen.getAllByTestId('catalog-versions-checkbox');
    fireEvent.click(checkboxes[0]);
    fireEvent.click(checkboxes[1]);
    // The third, unticked checkbox is disabled once two are chosen.
    expect(checkboxes[2]).toBeDisabled();
    // Unticking one re-enables it.
    fireEvent.click(checkboxes[1]);
    expect(checkboxes[2]).toBeEnabled();
  });

  it('surfaces a retryable error when the compare read fails', async () => {
    mockVersionsFetch(VERSIONS);
    mockLoadSpec.mockRejectedValue(new Error('spec boom'));
    render(<CatalogVersionsPanel itemId={ITEM_ID} active />);

    await screen.findByTestId('catalog-versions-timeline');
    fireEvent.click(screen.getAllByTestId('catalog-versions-checkbox')[0]);
    fireEvent.click(screen.getAllByTestId('catalog-versions-checkbox')[1]);

    expect(await screen.findByTestId('catalog-versions-diff-error')).toHaveTextContent('spec boom');
  });

  it('keeps the off-page history link as a fallback', async () => {
    mockVersionsFetch(VERSIONS);
    render(<CatalogVersionsPanel itemId={ITEM_ID} active />);

    const link = await screen.findByTestId('catalog-detail-versions-link');
    fireEvent.click(link);
    expect(mockPush).toHaveBeenCalledWith(
      `/ade/dashboard/versions?projectId=${encodeURIComponent(ITEM_ID)}`,
    );
  });

  it('shows an empty state when there are no revisions', async () => {
    mockVersionsFetch([]);
    render(<CatalogVersionsPanel itemId={ITEM_ID} active />);
    expect(await screen.findByTestId('catalog-versions-empty')).toBeInTheDocument();
  });

  it('surfaces a retryable error when the version fetch fails', async () => {
    mockVersionsFetch(null, false);
    render(<CatalogVersionsPanel itemId={ITEM_ID} active />);

    expect(await screen.findByTestId('catalog-versions-error')).toBeInTheDocument();

    // Retry re-fetches, this time succeeding.
    mockVersionsFetch(VERSIONS);
    fireEvent.click(screen.getByTestId('catalog-versions-retry'));
    await waitFor(() => expect(screen.getByTestId('catalog-versions-timeline')).toBeInTheDocument());
  });
});
