/**
 * Tests for QuickSnapshotGalleryDialog (#172, #174, #175)
 */
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import { QuickSnapshotGalleryDialog } from '../src/app/ade/studio/editor/components/QuickSnapshotGalleryDialog';
import type { QuickLayoutSnapshot } from '../src/app/ade/studio/editor/lib/quick-layout-snapshots';
import {
  QUICK_LAYOUT_SNAPSHOTS_SCHEMA_VERSION,
  QUICK_LAYOUT_SHARE_KIND,
  QUICK_LAYOUT_SHARE_SCHEMA_VERSION,
} from '../src/app/ade/studio/editor/lib/quick-layout-snapshots';

const noopAlert = async () => {};
const noopImport = async () => ({ success: true as const });

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
        versionId="version-1"
        onImportSharedJson={noopImport}
        alertDialog={noopAlert}
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
        versionId="version-1"
        onImportSharedJson={noopImport}
        alertDialog={noopAlert}
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
        versionId="version-1"
        onImportSharedJson={noopImport}
        alertDialog={noopAlert}
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
        versionId="version-1"
        onImportSharedJson={noopImport}
        alertDialog={noopAlert}
      />
    );
    expect(screen.getByRole('button', { name: /Restore quick snapshot/i })).toBeDisabled();
  });

  test('Share → Copy JSON calls clipboard.writeText with a JSON envelope and shows success alert', async () => {
    const user = userEvent.setup();
    const writeText = jest.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText },
      writable: true,
      configurable: true,
    });

    const alertCalls: Array<{ message: string; variant: string }> = [];
    const alertDialog = jest.fn(async (opts: { message: string; variant: string }) => {
      alertCalls.push(opts);
    });

    const snapshot = makeSnapshot('share-snap', '2026-03-01T10:00:00.000Z');

    render(
      <QuickSnapshotGalleryDialog
        open
        onOpenChange={() => {}}
        snapshots={[snapshot]}
        onRestore={() => {}}
        restoreDisabled={false}
        versionId="version-1"
        onImportSharedJson={noopImport}
        alertDialog={alertDialog}
      />
    );

    const shareBtn = screen.getByRole('button', { name: /Share snapshot/i });
    await user.click(shareBtn);

    const copyItem = await screen.findByText('Copy JSON');
    await user.click(copyItem);

    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
    const written = writeText.mock.calls[0][0] as string;
    const envelope = JSON.parse(written) as Record<string, unknown>;
    expect(envelope.kind).toBe(QUICK_LAYOUT_SHARE_KIND);
    expect(envelope.schemaVersion).toBe(QUICK_LAYOUT_SHARE_SCHEMA_VERSION);
    expect(envelope.versionId).toBe('version-1');

    await waitFor(() => expect(alertCalls.length).toBeGreaterThan(0));
    expect(alertCalls[0].variant).toBe('success');
  });

  test('Share → Pin as team default calls onPinTeamDefault when enabled', async () => {
    const user = userEvent.setup();
    const onPinTeamDefault = jest.fn();
    const snapshot = makeSnapshot('pin-snap', '2026-03-01T10:00:00.000Z');

    render(
      <QuickSnapshotGalleryDialog
        open
        onOpenChange={() => {}}
        snapshots={[snapshot]}
        onRestore={() => {}}
        restoreDisabled={false}
        versionId="version-1"
        onImportSharedJson={noopImport}
        alertDialog={noopAlert}
        pinTeamDefaultEnabled
        onPinTeamDefault={onPinTeamDefault}
      />
    );

    await user.click(screen.getByRole('button', { name: /Share snapshot/i }));
    const pinItem = await screen.findByText('Pin as team default');
    await user.click(pinItem);
    expect(onPinTeamDefault).toHaveBeenCalledTimes(1);
    expect(onPinTeamDefault).toHaveBeenCalledWith(expect.objectContaining({ id: 'pin-snap' }));
  });

  test('Import flow: success — calls onImportSharedJson and closes modal', async () => {
    const user = userEvent.setup();
    const onImportSharedJson = jest.fn().mockResolvedValue({ success: true as const });
    const alertCalls: Array<{ message: string; variant: string }> = [];
    const alertDialog = jest.fn(async (opts: { message: string; variant: string }) => {
      alertCalls.push(opts);
    });

    const snapshot = makeSnapshot('imp-snap', '2026-03-01T00:00:00.000Z');
    const validJson = JSON.stringify({
      kind: QUICK_LAYOUT_SHARE_KIND,
      schemaVersion: QUICK_LAYOUT_SHARE_SCHEMA_VERSION,
      versionId: 'version-1',
      snapshot,
    });

    render(
      <QuickSnapshotGalleryDialog
        open
        onOpenChange={() => {}}
        snapshots={[snapshot]}
        onRestore={() => {}}
        restoreDisabled={false}
        versionId="version-1"
        onImportSharedJson={onImportSharedJson}
        alertDialog={alertDialog}
      />
    );

    await user.click(screen.getByRole('button', { name: /Import shared snapshot/i }));

    const textarea = await screen.findByRole('textbox', { name: /Shared snapshot JSON/i });
    fireEvent.change(textarea, { target: { value: validJson } });

    await user.click(screen.getByRole('button', { name: /^Import$/i }));

    await waitFor(() => expect(onImportSharedJson).toHaveBeenCalledWith(validJson));
    await waitFor(() => expect(alertCalls.some((c) => c.variant === 'success')).toBe(true));
    await waitFor(() => expect(screen.queryByRole('dialog', { name: /Import shared snapshot/i })).not.toBeInTheDocument());
  });

  test('Import flow: error — shows error alert when onImportSharedJson returns failure', async () => {
    const user = userEvent.setup();
    const errorMsg = 'Version mismatch';
    const onImportSharedJson = jest.fn().mockResolvedValue({ success: false as const, message: errorMsg });
    const alertCalls: Array<{ message: string; variant: string }> = [];
    const alertDialog = jest.fn(async (opts: { message: string; variant: string }) => {
      alertCalls.push(opts);
    });

    const snapshot = makeSnapshot('err-snap', '2026-03-01T00:00:00.000Z');

    render(
      <QuickSnapshotGalleryDialog
        open
        onOpenChange={() => {}}
        snapshots={[snapshot]}
        onRestore={() => {}}
        restoreDisabled={false}
        versionId="version-1"
        onImportSharedJson={onImportSharedJson}
        alertDialog={alertDialog}
      />
    );

    await user.click(screen.getByRole('button', { name: /Import shared snapshot/i }));

    const textarea = await screen.findByRole('textbox', { name: /Shared snapshot JSON/i });
    fireEvent.change(textarea, { target: { value: '{ "some": "json" }' } });

    await user.click(screen.getByRole('button', { name: /^Import$/i }));

    await waitFor(() => expect(onImportSharedJson).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(alertCalls.some((c) => c.variant === 'error' && c.message === errorMsg)).toBe(true));
  });
});
