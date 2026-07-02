/**
 * Tests for QuickSnapshotCompareDialog (#171)
 */
import React from 'react';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import { QuickSnapshotCompareDialog } from '../src/app/ade/studio/editor/components/QuickSnapshotCompareDialog';
import type { QuickLayoutSnapshot } from '../src/app/ade/studio/editor/lib/quick-layout-snapshots';
import { QUICK_LAYOUT_SNAPSHOTS_SCHEMA_VERSION } from '../src/app/ade/studio/editor/lib/quick-layout-snapshots';

function makeSnapshot(
  id: string,
  createdAt: string,
  opts?: { thumb?: string; nodeCount?: number }
): QuickLayoutSnapshot {
  const n = opts?.nodeCount ?? 1;
  return {
    id,
    createdAt,
    ...(opts?.thumb ? { thumbnailDataUrl: opts.thumb } : {}),
    payload: {
      schemaVersion: QUICK_LAYOUT_SNAPSHOTS_SCHEMA_VERSION,
      viewport: { x: 0, y: 0, zoom: 1 },
      nodes: Array.from({ length: n }, (_, i) => ({ id: `n${i}` })),
      edges: [],
      groups: [],
    },
  };
}

describe('QuickSnapshotCompareDialog', () => {
  test('shows hint when fewer than two snapshots', () => {
    const one = makeSnapshot('a', '2026-03-01T10:00:00.000Z');
    render(
      <QuickSnapshotCompareDialog open onOpenChange={() => {}} snapshots={[one]} />
    );
    expect(screen.getByText(/Capture at least two quick snapshots/i)).toBeInTheDocument();
  });

  test('renders two panels and summary counts when comparing two snapshots', async () => {
    const user = userEvent.setup();
    const thumb = 'data:image/png;base64,iVBORw0KGgo=';
    const older = makeSnapshot('older', '2026-03-01T10:00:00.000Z', { thumb, nodeCount: 2 });
    const newer = makeSnapshot('newer', '2026-03-02T15:00:00.000Z', { nodeCount: 5 });

    render(
      <QuickSnapshotCompareDialog open onOpenChange={() => {}} snapshots={[newer, older]} />
    );

    expect(screen.getByText('Compare quick snapshots')).toBeInTheDocument();

    expect(screen.getAllByText(/2 nodes/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/5 nodes/).length).toBeGreaterThanOrEqual(1);

    await user.click(screen.getByRole('button', { name: /swap sides/i }));
    expect(screen.getByRole('button', { name: /swap sides/i })).toBeEnabled();
  });

  test('selectors list both snapshots', () => {
    const a = makeSnapshot('snap-a', '2026-01-01T08:00:00.000Z');
    const b = makeSnapshot('snap-b', '2026-01-02T08:00:00.000Z');
    render(<QuickSnapshotCompareDialog open onOpenChange={() => {}} snapshots={[b, a]} />);

    const combos = screen.getAllByRole('combobox');
    expect(combos).toHaveLength(2);
    for (const combo of combos) {
      const options = within(combo as HTMLElement).getAllByRole('option');
      expect(options).toHaveLength(2);
    }
  });
});
