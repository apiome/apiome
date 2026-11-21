'use client';

/**
 * The compare view's **Originals** mode (COA-5.7, #7083): a text diff of the two files the
 * compared versions were imported from, beside the semantic diff of their OpenAPI documents.
 *
 * Both originals are read through `/api/versions/[versionId]/original`, diffed by
 * {@link diffOriginals} (shared head and tail trimmed, the middle diffed asynchronously, long
 * unchanged runs collapsed), and drawn as a windowed list: only the rows near the viewport are
 * mounted, so a 20 MB pair scrolls without freezing the tab. A side with no stored original (or a
 * withheld one) says so instead of diffing against nothing.
 */

import * as React from 'react';
import { Download } from 'lucide-react';

import { Alert } from '@/app/components/ui/Alert';
import { Badge } from '@/app/components/ui/Badge';
import { Button } from '@/app/components/ui/Button';
import { EmptyState } from '@/app/components/ui/EmptyState';
import { LoadingState } from '@/app/components/ui/LoadingState';
import { diffOriginals, type OriginalDiff, type OriginalDiffRow } from '@/app/utils/original-text-diff';
import { computeWindowedRange } from '@/app/utils/windowed-rows';
import {
  downloadVersionOriginal,
  fetchVersionOriginalText,
  type OriginalFailure,
  type OriginalText,
} from '@/app/utils/version-original';
import { toast } from '../../ui/toast';

/** One side of the comparison. */
export interface OriginalSide {
  projectId: string;
  versionId: string;
  /** The version label shown in the header, e.g. `v1.2.0`. */
  label: string;
}

export interface OriginalsDiffPanelProps {
  /** The base (left) version. */
  base: OriginalSide;
  /** The compare-to (right) version. */
  head: OriginalSide;
}

/** Row height used before the first row has been measured, in px. */
const DEFAULT_ROW_HEIGHT = 20;

type LoadState =
  | { status: 'loading' }
  | { status: 'failed'; base: OriginalText | OriginalFailure; head: OriginalText | OriginalFailure }
  | { status: 'ready'; base: OriginalText; head: OriginalText; diff: OriginalDiff };

function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function prefix(kind: 'context' | 'added' | 'removed'): string {
  return kind === 'added' ? '+' : kind === 'removed' ? '-' : ' ';
}

/** One drawn row of the diff. */
function DiffRow({ row }: { row: OriginalDiffRow }) {
  if (row.kind === 'skip') {
    return (
      <div className="vdlg-origdiff__row vdlg-origdiff__skip" data-testid="originals-diff-skip">
        {`⋯ ${row.count.toLocaleString()} unchanged line${row.count === 1 ? '' : 's'}`}
      </div>
    );
  }
  return (
    <div className="vdlg-origdiff__row vdlg-diff__line" data-change={row.kind === 'context' ? undefined : row.kind}>
      <span className="vdlg-diff__ln">{row.leftLine ?? ''}</span>
      <span className="vdlg-diff__ln">{row.rightLine ?? ''}</span>
      {`${prefix(row.kind)} ${row.text}`}
    </div>
  );
}

/**
 * Render the Originals mode. See {@link OriginalsDiffPanelProps}.
 *
 * @returns The panel.
 */
export default function OriginalsDiffPanel({ base, head }: OriginalsDiffPanelProps) {
  const [state, setState] = React.useState<LoadState>({ status: 'loading' });
  const [attempt, setAttempt] = React.useState(0);
  const [scrollTop, setScrollTop] = React.useState(0);
  const [viewportHeight, setViewportHeight] = React.useState(0);
  const [rowHeight, setRowHeight] = React.useState(DEFAULT_ROW_HEIGHT);
  const scrollerRef = React.useRef<HTMLDivElement | null>(null);

  React.useEffect(() => {
    const controller = new AbortController();
    setState({ status: 'loading' });
    (async () => {
      const [left, right] = await Promise.all([
        fetchVersionOriginalText(base.projectId, base.versionId, controller.signal),
        fetchVersionOriginalText(head.projectId, head.versionId, controller.signal),
      ]);
      if (!left.ok || !right.ok) {
        setState({ status: 'failed', base: left, head: right });
        return;
      }
      const diff = await diffOriginals(left.text, right.text, { signal: controller.signal });
      setState({ status: 'ready', base: left, head: right, diff });
    })().catch((error: unknown) => {
      if ((error as Error)?.name === 'AbortError') return;
      setState({
        status: 'failed',
        base: { ok: false, status: 0, error: 'The originals could not be compared.' },
        head: { ok: false, status: 0, error: 'The originals could not be compared.' },
      });
    });
    return () => controller.abort();
  }, [base.projectId, base.versionId, head.projectId, head.versionId, attempt]);

  // Measure the viewport and one row once the rows are drawn, so the window matches the CSS.
  React.useLayoutEffect(() => {
    const scroller = scrollerRef.current;
    if (!scroller) return;
    setViewportHeight(scroller.clientHeight);
    const first = scroller.querySelector<HTMLElement>('.vdlg-origdiff__row');
    if (first && first.offsetHeight > 0) setRowHeight(first.offsetHeight);
  }, [state.status]);

  const rows = state.status === 'ready' ? state.diff.rows : [];
  const windowed = React.useMemo(
    () => computeWindowedRange({ rowCount: rows.length, rowHeight, viewportHeight, scrollTop, overscan: 20 }),
    [rows.length, rowHeight, viewportHeight, scrollTop],
  );

  const download = async (side: OriginalSide) => {
    const result = await downloadVersionOriginal(side.projectId, side.versionId);
    if (!result.ok) toast.error(result.error);
  };

  if (state.status === 'loading') {
    return (
      <LoadingState
        className="vdlg-origdiff__state"
        spinnerSize="md"
        message="Reading and comparing the original files…"
        data-testid="originals-diff-loading"
      />
    );
  }

  if (state.status === 'failed') {
    const sides: [OriginalSide, OriginalText | OriginalFailure][] = [
      [base, state.base],
      [head, state.head],
    ];
    return (
      <div className="vdlg-origdiff__state" data-testid="originals-diff-unavailable">
        <EmptyState
          title="These originals can't be compared"
          description={sides
            .filter(([, result]) => !result.ok)
            .map(([side, result]) => `${side.label}: ${(result as OriginalFailure).error}`)
            .join(' ')}
          action={
            <Button variant="outline" size="sm" onClick={() => setAttempt((n) => n + 1)}>
              Try again
            </Button>
          }
        />
      </div>
    );
  }

  const { diff } = state;
  return (
    <div className="vdlg-origdiff" data-testid="originals-diff">
      <div className="vdlg-origdiff__head">
        <div className="vdlg-origdiff__files">
          {[
            [base, state.base, 'base'],
            [head, state.head, 'compare to'],
          ].map(([side, file, role]) => {
            const s = side as OriginalSide;
            const f = file as OriginalText;
            return (
              <span key={role as string} className="vdlg-origdiff__file">
                <span className="vdlg-caps">{`${s.label} (${role as string})`}</span>
                <span className="mono">{f.filename}</span>
                <span className="hive-quiet">{formatBytes(f.size)}</span>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => void download(s)}
                  aria-label={`Download the original of ${s.label}`}
                >
                  <Download aria-hidden />
                </Button>
              </span>
            );
          })}
        </div>
        <div className="vdlg-origdiff__counts" data-testid="originals-diff-counts">
          {diff.identical ? (
            <Badge variant="success">Identical files</Badge>
          ) : (
            <>
              <span className="vdlg-stat">+{diff.added.toLocaleString()}</span>
              <span className="vdlg-stat">−{diff.removed.toLocaleString()}</span>
            </>
          )}
        </div>
      </div>
      {diff.approximate ? (
        <Alert variant="warning" data-testid="originals-diff-approximate">
          These files differ too much to line up in time, so the changed part is shown as removed and
          re-added in full.
        </Alert>
      ) : null}
      <div
        ref={scrollerRef}
        className="vdlg-diff vdlg-origdiff__scroll"
        onScroll={(event) => setScrollTop(event.currentTarget.scrollTop)}
        role="region"
        aria-label={`Text diff of the original files of ${base.label} and ${head.label}`}
        tabIndex={0}
        data-testid="originals-diff-rows"
        data-row-count={rows.length}
      >
        <div style={{ height: windowed.paddingTop }} aria-hidden />
        {rows.slice(windowed.startIndex, windowed.endIndex).map((row, i) => (
          <DiffRow key={windowed.startIndex + i} row={row} />
        ))}
        <div style={{ height: windowed.paddingBottom }} aria-hidden />
      </div>
    </div>
  );
}
