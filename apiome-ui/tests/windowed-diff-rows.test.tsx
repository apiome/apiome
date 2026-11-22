/**
 * The compare view's rendered diff pane (COA-5.13, #7089).
 *
 * A short diff mounts every row, wrapped, as before. Above the threshold the pane is windowed:
 * only the rows near the viewport are mounted, with spacers that keep the scrollbar's length, and
 * scrolling moves the window. jsdom has no layout, so the pane's height is set by hand.
 */

import React from 'react';
import { describe, expect, it, jest } from '@jest/globals';
import { act, fireEvent, render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';

import type { VersionDiffRow } from '../src/app/components/ade/version-dialogs/versionDialogsModel';
import {
  DiffRowView,
  WINDOWED_DIFF_THRESHOLD,
  WindowedDiffRows,
} from '../src/app/components/ade/versions/WindowedDiffRows';

function lines(count: number): VersionDiffRow[] {
  return Array.from({ length: count }, (_, i) => ({
    kind: 'line' as const,
    change: i % 10 === 0 ? ('added' as const) : ('unchanged' as const),
    text: `line ${i}`,
    lineNo: i + 1,
  }));
}

/** Give the pane a height (jsdom reports 0) and re-render so the window is computed from it. */
function withViewport(height: number, ui: React.ReactElement) {
  const spy = jest.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockReturnValue(height);
  const view = render(ui);
  spy.mockRestore();
  return view;
}

describe('DiffRowView', () => {
  it('draws a line with its change and, in the split view, its number', () => {
    const { container } = render(
      <DiffRowView row={{ kind: 'line', change: 'removed', text: 'old', lineNo: 7 }} showLineNo />,
    );
    const line = container.querySelector('.vdlg-diff__line')!;
    expect(line).toHaveAttribute('data-change', 'removed');
    expect(line).toHaveTextContent('7old');
  });

  it('prefixes the change sign in the overlay view', () => {
    const { container } = render(
      <DiffRowView
        row={{ kind: 'line', change: 'added', text: 'new', lineNo: 1 }}
        showLineNo={false}
      />,
    );
    expect(container.querySelector('.vdlg-diff__line')!.textContent).toBe('+ new');
  });

  it('draws a fold for hidden unchanged lines', () => {
    const { container } = render(
      <DiffRowView row={{ kind: 'fold', hidden: 1204 }} showLineNo={false} />,
    );
    expect(container.querySelector('.vdlg-diff__fold')).toHaveTextContent('1,204 unchanged lines');
  });
});

describe('WindowedDiffRows', () => {
  it('mounts every row of a short diff, without the windowed modifier', () => {
    const { container } = render(
      <WindowedDiffRows
        rows={lines(40)}
        showLineNo={false}
        className="vdlg-diff__scroll"
        testId="pane"
      />,
    );
    const pane = screen.getByTestId('pane');
    expect(pane).toHaveClass('vdlg-diff__scroll');
    expect(pane).not.toHaveClass('vdlg-diff--windowed');
    expect(pane).not.toHaveAttribute('data-windowed');
    expect(pane).toHaveAttribute('data-row-count', '40');
    expect(container.querySelectorAll('.vdlg-diff__line')).toHaveLength(40);
  });

  it('mounts only the rows near the viewport of a long diff', () => {
    const total = WINDOWED_DIFF_THRESHOLD + 5000;
    const { container } = withViewport(
      400,
      <WindowedDiffRows
        rows={lines(total)}
        showLineNo={false}
        className="vdlg-diff__scroll"
        testId="pane"
      />,
    );
    const pane = screen.getByTestId('pane');
    expect(pane).toHaveClass('vdlg-diff--windowed');
    expect(pane).toHaveAttribute('data-windowed', 'true');
    expect(pane).toHaveAttribute('data-row-count', String(total));

    const mounted = container.querySelectorAll('.vdlg-diff__line');
    expect(mounted.length).toBeGreaterThan(0);
    expect(mounted.length).toBeLessThan(200);
    expect(mounted[0]).toHaveTextContent('line 0');
    // The spacer below stands in for the rows that are not mounted.
    const spacers = [...pane.querySelectorAll<HTMLElement>('[aria-hidden]')];
    expect(spacers).toHaveLength(1);
    expect(parseInt(spacers[0].style.height, 10)).toBe((total - mounted.length) * 20);
  });

  it('moves the window when the pane scrolls, and tells the caller', () => {
    const onScroll = jest.fn();
    const total = WINDOWED_DIFF_THRESHOLD + 5000;
    const { container } = withViewport(
      400,
      <WindowedDiffRows
        rows={lines(total)}
        showLineNo
        className="vdlg-diff__pane"
        testId="pane"
        onScroll={onScroll}
      />,
    );
    const pane = screen.getByTestId('pane');

    act(() => {
      pane.scrollTop = 20 * 3000;
      fireEvent.scroll(pane);
    });

    expect(onScroll).toHaveBeenCalledTimes(1);
    const mounted = [...container.querySelectorAll('.vdlg-diff__line')].map(
      (row) => row.textContent,
    );
    expect(mounted).toContain('3001line 3000');
    expect(mounted).not.toContain('1line 0');
    expect(pane.querySelectorAll('[aria-hidden]')).toHaveLength(2);
  });

  it('hands the pane element to the caller and draws the sticky title above the rows', () => {
    const paneRef = React.createRef<HTMLDivElement>();
    render(
      <WindowedDiffRows
        rows={lines(3)}
        showLineNo
        className="vdlg-diff__pane"
        paneRef={paneRef}
        title={<div className="vdlg-diff__pane-title">v1.0.0 (base)</div>}
        testId="pane"
      />,
    );
    const pane = screen.getByTestId('pane');
    expect(paneRef.current).toBe(pane);
    expect(pane.firstElementChild).toHaveTextContent('v1.0.0 (base)');
  });

  it('mounts everything when the pane cannot be measured, rather than truncating', () => {
    const total = WINDOWED_DIFF_THRESHOLD + 10;
    const { container } = render(
      <WindowedDiffRows rows={lines(total)} showLineNo={false} className="vdlg-diff__scroll" />,
    );
    expect(container.querySelectorAll('.vdlg-diff__line')).toHaveLength(total);
  });
});
