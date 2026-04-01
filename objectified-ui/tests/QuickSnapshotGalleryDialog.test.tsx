/**
 * Tests for QuickSnapshotGalleryDialog (#172)
 */
import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import { QuickSnapshotGalleryDialog } from '../src/app/ade/studio/editor/components/QuickSnapshotGalleryDialog';
import type { QuickLayoutSnapshot } from '../src/app/ade/studio/editor/lib/quick-layout-snapshots';
import { QUICK_LAYOUT_SNAPSHOTS_SCHEMA_VERSION } from '../src/app/ade/studio/editor/lib/quick-layout-snapshots';

function makeSnapshot(
  id: string,
  createdAt: string,
  opts?: { withThumb?: boolean; nodeCount?: number }
): QuickLayoutSnapshot {
  const n = opts?.nodeCount ?? 1;
  const out: QuickLayoutSnapshot = {
    id,
    createdAt,
    payload: {
      schemaVersion: QUICK_LAYOUT_SNAPSHOTS_SCHEMA_VERSION,
      viewport: { x: 0, y: 0, zoom: 1 },
      nodes: Array.from({ length: n }, (_, i) => ({ id: `n${i}` })),
      edges: [],
      groups: [],
    },
  };
  if (opts?.withThumb) {
    out.thumbnailDataUrl = 'data:image/png;base64,iVBORw0KGgo=';
  }
  return out;
}

describe('QuickSnapshotGalleryDialog', () => {
  test('shows empty state when there are no snapshots', () => {
    render(
      <QuickSnapshotGalleryDialog
        open
        onOpenChange={() => {}}
        snapshots={[]}
        onRestore={() => {}}
        restoreDisabled={false}
      />
    );
    expect(screen.getByText(/No quick snapshots yet/i)).toBeInTheDocument();
  });

  test('filters by search query on summary text', async () => {
    const user = userEvent.setup();
    const a = makeSnapshot('alpha-snap', '2026-03-01T10:00:00.000Z', { nodeCount: 2 });
    a.summary = 'Payment flow draft';
    const b = makeSnapshot('beta-snap', '2026-03-02T10:00:00.000Z', { nodeCount: 5 });

    render(
      <QuickSnapshotGalleryDialog
        open
        onOpenChange={() => {}}
        snapshots={[b, a]}
        onRestore={() => {}}
        restoreDisabled={false}
      />
    );

    expect(screen.getByText(/Showing 2 of 2/i)).toBeInTheDocument();
    const search = screen.getByRole('searchbox', { name: /Search quick snapshots/i });
    await user.type(search, 'payment');
    expect(screen.getByText(/Showing 1 of 2/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Restore quick snapshot/i)).toBeInTheDocument();
  });

  test('filters by preview toggle and calls onRestore', async () => {
    const user = userEvent.setup();
    const withThumb = makeSnapshot('has-thumb', '2026-01-01T00:00:00.000Z', { withThumb: true });
    const noThumb = makeSnapshot('no-thumb', '2026-01-02T00:00:00.000Z');
    const onRestore = jest.fn();

    render(
      <QuickSnapshotGalleryDialog
        open
        onOpenChange={() => {}}
        snapshots={[withThumb, noThumb]}
        onRestore={onRestore}
        restoreDisabled={false}
      />
    );

    await user.click(screen.getByRole('radio', { name: /No image/i }));
    expect(screen.getByText(/Showing 1 of 2/i)).toBeInTheDocument();
    const restoreBtn = screen.getByLabelText(/Restore quick snapshot/i);
    await user.click(restoreBtn);
    expect(onRestore).toHaveBeenCalledWith(expect.objectContaining({ id: 'no-thumb' }));
  });

  test('restore buttons disabled when restoreDisabled', () => {
    const s = makeSnapshot('s1', '2026-01-01T00:00:00.000Z');
    render(
      <QuickSnapshotGalleryDialog
        open
        onOpenChange={() => {}}
        snapshots={[s]}
        onRestore={() => {}}
        restoreDisabled
        restoreDisabledReason="Read-only"
      />
    );
    expect(screen.getByRole('button', { name: /Restore quick snapshot/i })).toBeDisabled();
  });
});
