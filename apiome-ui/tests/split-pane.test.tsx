/**
 * SplitPane (SUX-3.4, apiome#6754).
 *
 * 1. **Pure helpers.** Pane-list validation, clamping, the grid template, which pane a handle
 *    sizes, and sanitising whatever storage holds.
 * 2. **Separator semantics and keyboard.** `role="separator"` with values; ←/→ (and Shift), Home,
 *    End, Enter (collapse) and double-click (reset).
 * 3. **Pointer drag.** Moving the handle resizes and clamps; a collapsible pane collapses when
 *    dragged under half its minimum; the root marks itself as dragging.
 * 4. **Persistence.** The layout is written under `apiome:split-pane:<key>` and restored; junk and
 *    throwing storage are ignored.
 * 5. **Identity.** Resizing never remounts a pane's content (an iframe keeps its node).
 * 6. **CSS.** The "SPLIT PANE (SUX-3.4)" section of `globals.css` uses the column variable.
 */

import * as React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';

import {
  SPLIT_PANE_STORAGE_PREFIX,
  SplitPane,
  clampPaneSize,
  flexPaneIndex,
  handleTarget,
  readSplitPaneLayout,
  sanitizeSplitPaneLayout,
  splitPaneColumns,
  type SplitPaneConfig,
} from '../src/app/components/ui';
import { readGlobalsCss } from './helpers/design-tokens';

const FORM: SplitPaneConfig = {
  id: 'form',
  label: 'Form',
  defaultSize: 360,
  minSize: 280,
  maxSize: 520,
  collapsible: true,
};
const PREVIEW: SplitPaneConfig = { id: 'preview', label: 'Preview' };
const INSPECTOR: SplitPaneConfig = { id: 'inspector', label: 'Inspector', defaultSize: 300, minSize: 240, maxSize: 400 };

/** The grid element's column template variable. */
function columns(): string {
  const grid = document.querySelector('.hive-split-pane__grid') as HTMLElement;
  return grid.style.getPropertyValue('--split-pane-columns');
}

/**
 * Render a two-pane split (form + preview).
 *
 * @param props Extra props for the split pane.
 * @returns The render result.
 */
function renderTwo(props: Partial<React.ComponentProps<typeof SplitPane>> = {}) {
  return render(
    <SplitPane aria-label="Editor" panes={[FORM, PREVIEW]} {...props}>
      <div>form body</div>
      <iframe title="preview frame" />
    </SplitPane>,
  );
}

/**
 * jsdom has no `PointerEvent`, so `fireEvent.pointer*` would drop `pointerId`, `button` and
 * `clientX`. A minimal subclass of `MouseEvent` that keeps `pointerId` is enough here.
 */
beforeAll(() => {
  if (typeof window.PointerEvent === 'undefined') {
    class TestPointerEvent extends MouseEvent {
      pointerId: number;
      constructor(type: string, init: PointerEventInit = {}) {
        super(type, init);
        this.pointerId = init.pointerId ?? 0;
      }
    }
    (window as unknown as { PointerEvent: unknown }).PointerEvent = TestPointerEvent;
  }
});

beforeEach(() => {
  window.localStorage.clear();
});

describe('helpers', () => {
  it('finds the one flexible pane and rejects bad pane lists', () => {
    expect(flexPaneIndex([FORM, PREVIEW])).toBe(1);
    expect(flexPaneIndex([FORM, PREVIEW, INSPECTOR])).toBe(1);
    expect(() => flexPaneIndex([PREVIEW])).toThrow(/two or three/);
    expect(() => flexPaneIndex([FORM, INSPECTOR])).toThrow(/exactly one/);
    expect(() => flexPaneIndex([PREVIEW, { ...PREVIEW }])).toThrow(/unique/);
  });

  it('clamps to min and max and rounds', () => {
    expect(clampPaneSize(FORM, 100)).toBe(280);
    expect(clampPaneSize(FORM, 9000)).toBe(520);
    expect(clampPaneSize(FORM, 333.6)).toBe(334);
    expect(clampPaneSize({ id: 'x', label: 'X', defaultSize: 1 }, 50)).toBe(120);
  });

  it('builds the grid template with an auto column per handle', () => {
    const layout = { sizes: { form: 360, inspector: 300 }, collapsed: {} };
    expect(splitPaneColumns([FORM, PREVIEW, INSPECTOR], layout)).toBe(
      '360px auto minmax(0, 1fr) auto 300px',
    );
    expect(splitPaneColumns([FORM, PREVIEW], { ...layout, collapsed: { form: true } })).toBe(
      '0px auto minmax(0, 1fr)',
    );
  });

  it('sizes the fixed neighbour of each handle', () => {
    expect(handleTarget(0, 1)).toEqual({ index: 0, sign: 1 });
    expect(handleTarget(1, 1)).toEqual({ index: 2, sign: -1 });
    expect(handleTarget(0, 0)).toEqual({ index: 1, sign: -1 });
  });

  it('keeps only valid stored values', () => {
    expect(sanitizeSplitPaneLayout([FORM, PREVIEW], 'junk')).toEqual({ sizes: { form: 360 }, collapsed: {} });
    expect(
      sanitizeSplitPaneLayout([FORM, PREVIEW, INSPECTOR], {
        sizes: { form: 9999, inspector: 'wide', preview: 10, ghost: 5 },
        collapsed: { form: true, inspector: true },
      }),
    ).toEqual({ sizes: { form: 520, inspector: 300 }, collapsed: { form: true } });
  });

  it('falls back to defaults when storage throws', () => {
    const spy = jest.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    expect(readSplitPaneLayout('k', [FORM, PREVIEW])).toEqual({ sizes: { form: 360 }, collapsed: {} });
    spy.mockRestore();
  });
});

describe('<SplitPane>', () => {
  it('renders a labelled vertical separator with its values', () => {
    renderTwo();
    const handle = screen.getByRole('separator', { name: 'Resize Form' });
    expect(handle).toHaveAttribute('aria-orientation', 'vertical');
    expect(handle).toHaveAttribute('aria-valuenow', '360');
    expect(handle).toHaveAttribute('aria-valuemin', '0');
    expect(handle).toHaveAttribute('aria-valuemax', '520');
    expect(handle.getAttribute('aria-controls')).toBe(
      document.querySelector('[data-pane="form"]')?.id,
    );
    expect(columns()).toBe('360px auto minmax(0, 1fr)');
  });

  it('resizes with the arrow keys, Shift, Home and End', () => {
    renderTwo();
    const handle = screen.getByRole('separator');
    fireEvent.keyDown(handle, { key: 'ArrowRight' });
    expect(handle).toHaveAttribute('aria-valuenow', '376');
    fireEvent.keyDown(handle, { key: 'ArrowLeft', shiftKey: true });
    expect(handle).toHaveAttribute('aria-valuenow', '312');
    fireEvent.keyDown(handle, { key: 'Home' });
    expect(handle).toHaveAttribute('aria-valuenow', '280');
    fireEvent.keyDown(handle, { key: 'End' });
    expect(handle).toHaveAttribute('aria-valuenow', '520');
    expect(columns()).toBe('520px auto minmax(0, 1fr)');
  });

  it('moves a right-hand pane the other way', () => {
    render(
      <SplitPane panes={[FORM, PREVIEW, INSPECTOR]}>
        <div />
        <div />
        <div />
      </SplitPane>,
    );
    const handle = screen.getByRole('separator', { name: 'Resize Inspector' });
    fireEvent.keyDown(handle, { key: 'ArrowRight' });
    expect(handle).toHaveAttribute('aria-valuenow', '284');
  });

  it('collapses and restores a collapsible pane with Enter', () => {
    renderTwo();
    const handle = screen.getByRole('separator');
    fireEvent.keyDown(handle, { key: 'Enter' });
    expect(handle).toHaveAttribute('aria-valuenow', '0');
    expect(handle).toHaveAttribute('aria-valuetext', 'Form collapsed');
    expect(document.querySelector('[data-pane="form"]')).toHaveAttribute('aria-hidden', 'true');
    expect(columns()).toBe('0px auto minmax(0, 1fr)');
    fireEvent.keyDown(handle, { key: 'Enter' });
    expect(handle).toHaveAttribute('aria-valuenow', '360');
  });

  it('ignores Enter on a pane that cannot collapse', () => {
    render(
      <SplitPane panes={[{ ...FORM, collapsible: false }, PREVIEW]}>
        <div />
        <div />
      </SplitPane>,
    );
    const handle = screen.getByRole('separator');
    fireEvent.keyDown(handle, { key: 'Enter' });
    expect(handle).toHaveAttribute('aria-valuenow', '360');
    expect(handle).toHaveAttribute('aria-valuemin', '280');
  });

  it('drags with the pointer, clamps, and collapses under half the minimum', () => {
    renderTwo();
    const handle = screen.getByRole('separator');
    const grid = document.querySelector('.hive-split-pane__grid')!;
    fireEvent.pointerDown(handle, { pointerId: 1, button: 0, clientX: 400 });
    expect(grid).toHaveAttribute('data-dragging', 'true');
    fireEvent.pointerMove(handle, { pointerId: 1, clientX: 450 });
    expect(handle).toHaveAttribute('aria-valuenow', '410');
    fireEvent.pointerMove(handle, { pointerId: 1, clientX: 2000 });
    expect(handle).toHaveAttribute('aria-valuenow', '520');
    fireEvent.pointerMove(handle, { pointerId: 1, clientX: 200 });
    expect(handle).toHaveAttribute('aria-valuenow', '280');
    fireEvent.pointerMove(handle, { pointerId: 1, clientX: 0 });
    expect(handle).toHaveAttribute('aria-valuetext', 'Form collapsed');
    fireEvent.pointerUp(handle, { pointerId: 1 });
    expect(grid).not.toHaveAttribute('data-dragging');
    // A move after release does nothing.
    fireEvent.pointerMove(handle, { pointerId: 1, clientX: 900 });
    expect(handle).toHaveAttribute('aria-valuetext', 'Form collapsed');
  });

  it('resets to the default width on double-click', () => {
    renderTwo();
    const handle = screen.getByRole('separator');
    fireEvent.keyDown(handle, { key: 'End' });
    fireEvent.doubleClick(handle);
    expect(handle).toHaveAttribute('aria-valuenow', '360');
  });

  it('persists the layout per key and restores it', () => {
    const onLayoutChange = jest.fn();
    const { unmount } = renderTwo({ storageKey: 'slate-theme', onLayoutChange });
    fireEvent.keyDown(screen.getByRole('separator'), { key: 'End' });
    expect(onLayoutChange).toHaveBeenLastCalledWith({ sizes: { form: 520 }, collapsed: { form: false } });
    expect(JSON.parse(window.localStorage.getItem(`${SPLIT_PANE_STORAGE_PREFIX}slate-theme`)!)).toEqual({
      sizes: { form: 520 },
      collapsed: { form: false },
    });
    unmount();

    renderTwo({ storageKey: 'slate-theme' });
    expect(screen.getByRole('separator')).toHaveAttribute('aria-valuenow', '520');
  });

  it('keeps separate widths for separate keys and ignores junk', () => {
    window.localStorage.setItem(`${SPLIT_PANE_STORAGE_PREFIX}a`, JSON.stringify({ sizes: { form: 300 } }));
    window.localStorage.setItem(`${SPLIT_PANE_STORAGE_PREFIX}b`, '{not json');
    const { unmount } = renderTwo({ storageKey: 'a' });
    expect(screen.getByRole('separator')).toHaveAttribute('aria-valuenow', '300');
    unmount();
    renderTwo({ storageKey: 'b' });
    expect(screen.getByRole('separator')).toHaveAttribute('aria-valuenow', '360');
  });

  it('does not remount pane content when resized', () => {
    renderTwo();
    const frame = screen.getByTitle('preview frame');
    const handle = screen.getByRole('separator');
    fireEvent.keyDown(handle, { key: 'End' });
    fireEvent.keyDown(handle, { key: 'Enter' });
    fireEvent.keyDown(handle, { key: 'Enter' });
    expect(screen.getByTitle('preview frame')).toBe(frame);
  });

  it('throws when the children do not match the panes', () => {
    const spy = jest.spyOn(console, 'error').mockImplementation(() => undefined);
    expect(() =>
      render(
        <SplitPane panes={[FORM, PREVIEW]}>
          <div />
        </SplitPane>,
      ),
    ).toThrow(/2 panes but 1 children/);
    spy.mockRestore();
  });
});

describe('globals.css SPLIT PANE section', () => {
  const css = readGlobalsCss();
  const start = css.indexOf('SPLIT PANE (SUX-3.4');
  const section = css.slice(start, css.indexOf('/* ====', start));

  it('drives the grid from the column variable and stacks narrow containers', () => {
    expect(start).toBeGreaterThan(0);
    expect(section).toContain('grid-template-columns: var(--split-pane-columns)');
    expect(section).toMatch(/@container split-pane \(max-width: 40rem\)/);
    expect(section).toMatch(/\[data-dragging\] iframe\s*\{\s*pointer-events: none/);
  });
});
