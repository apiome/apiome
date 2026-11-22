'use client';

/**
 * One scrolling pane of the compare view's rendered diff (COA-5.13, #7089).
 *
 * A revision's OpenAPI document can run to hundreds of thousands of lines. Mounting a DOM node for
 * every diff row freezes the tab, so a long diff is **windowed**: only the rows near the viewport
 * are mounted, with a spacer above and below so the scrollbar keeps its true length
 * ({@link computeWindowedRange}).
 *
 * Windowing needs rows of one height, so above {@link WINDOWED_DIFF_THRESHOLD} rows the pane takes
 * the `vdlg-diff--windowed` modifier: each line is one non-wrapping row and the pane scrolls
 * sideways for long lines. A shorter diff is drawn as before, with wrapped lines and every row
 * mounted.
 */

import * as React from 'react';

import {
  diffLinePrefix,
  versionDiffFoldLabel,
  type VersionDiffRow,
} from '@/app/components/ade/version-dialogs/versionDialogsModel';
import { computeWindowedRange } from '@/app/utils/windowed-rows';

/** Above this many rows a pane is windowed. */
export const WINDOWED_DIFF_THRESHOLD = 1500;
/** Row height used before a row has been measured, in px. */
const DEFAULT_ROW_HEIGHT = 20;
/** Rows mounted above and below the viewport. */
const OVERSCAN_ROWS = 30;

export interface WindowedDiffRowsProps {
  /** The rows to draw, from `buildVersionDiffRows`. */
  rows: readonly VersionDiffRow[];
  /** Draw the gutter line number (the split view does; the overlay prefixes `+` / `-` instead). */
  showLineNo: boolean;
  /** The scrolling pane's class (`vdlg-diff__scroll` or `vdlg-diff__pane …`). */
  className: string;
  /** A sticky heading drawn above the rows (the split view's version label). */
  title?: React.ReactNode;
  /** The pane element, for the split view's scroll sync. */
  paneRef?: React.Ref<HTMLDivElement>;
  /** Called on scroll, after the pane's own bookkeeping. */
  onScroll?: () => void;
  /** Test id of the pane. */
  testId?: string;
}

/**
 * One drawn diff row: a spec line, or a fold standing in for unchanged lines.
 *
 * @param props.row The row.
 * @param props.showLineNo Draw the gutter line number.
 * @returns The row's element.
 */
export function DiffRowView({ row, showLineNo }: { row: VersionDiffRow; showLineNo: boolean }) {
  if (row.kind === 'fold') {
    return <div className="vdlg-diff__fold">{versionDiffFoldLabel(row.hidden)}</div>;
  }
  return (
    <div className="vdlg-diff__line" data-change={row.change}>
      {showLineNo ? <span className="vdlg-diff__ln">{row.lineNo}</span> : null}
      {showLineNo ? row.text || ' ' : `${diffLinePrefix(row.change)}${row.text}`}
    </div>
  );
}

/**
 * Draw one pane of diff rows, windowed when there are many.
 *
 * @param props See {@link WindowedDiffRowsProps}.
 * @returns The scrolling pane.
 */
export function WindowedDiffRows({
  rows,
  showLineNo,
  className,
  title,
  paneRef,
  onScroll,
  testId,
}: WindowedDiffRowsProps) {
  const windowedMode = rows.length > WINDOWED_DIFF_THRESHOLD;
  const innerRef = React.useRef<HTMLDivElement | null>(null);
  const [scrollTop, setScrollTop] = React.useState(0);
  const [viewportHeight, setViewportHeight] = React.useState(0);
  const [rowHeight, setRowHeight] = React.useState(DEFAULT_ROW_HEIGHT);

  // Hand the pane element to the caller (the split view syncs the two panes' scroll offsets).
  React.useImperativeHandle<HTMLDivElement | null, HTMLDivElement | null>(
    paneRef,
    () => innerRef.current,
    [],
  );

  // Measure the viewport and one row once the rows are drawn, so the window matches the CSS.
  React.useLayoutEffect(() => {
    const pane = innerRef.current;
    if (!pane || !windowedMode) return;
    setViewportHeight(pane.clientHeight);
    const first = pane.querySelector<HTMLElement>('.vdlg-diff__line');
    if (first && first.offsetHeight > 0) setRowHeight(first.offsetHeight);
  }, [windowedMode, rows]);

  // A new diff starts at its top.
  React.useEffect(() => {
    if (innerRef.current) innerRef.current.scrollTop = 0;
    setScrollTop(0);
  }, [rows]);

  const range = React.useMemo(
    () =>
      windowedMode
        ? computeWindowedRange({
            rowCount: rows.length,
            rowHeight,
            viewportHeight,
            scrollTop,
            overscan: OVERSCAN_ROWS,
          })
        : { startIndex: 0, endIndex: rows.length, paddingTop: 0, paddingBottom: 0 },
    [windowedMode, rows.length, rowHeight, viewportHeight, scrollTop],
  );

  return (
    <div
      ref={innerRef}
      className={windowedMode ? `${className} vdlg-diff--windowed` : className}
      onScroll={(event) => {
        if (windowedMode) setScrollTop(event.currentTarget.scrollTop);
        onScroll?.();
      }}
      data-testid={testId}
      data-row-count={rows.length}
      data-windowed={windowedMode ? 'true' : undefined}
    >
      {title}
      {range.paddingTop > 0 ? <div style={{ height: range.paddingTop }} aria-hidden /> : null}
      {rows.slice(range.startIndex, range.endIndex).map((row, i) => (
        <DiffRowView key={range.startIndex + i} row={row} showLineNo={showLineNo} />
      ))}
      {range.paddingBottom > 0 ? <div style={{ height: range.paddingBottom }} aria-hidden /> : null}
    </div>
  );
}

export default WindowedDiffRows;
