'use client';

import * as React from 'react';
import { cn } from '../../../../lib/utils';

/**
 * SplitPane — two or three panes side by side with drag handles between them (SUX-3.4,
 * apiome#6754).
 *
 * Before this, every editor that sat a form beside a preview fixed its own column width (320,
 * 416 or 320 px) and none of them resized. The split pane gives one behaviour to all of them:
 *
 * - **One flexible pane.** Exactly one pane has no `defaultSize`; it takes the space that is
 *   left. Every other pane has a width in px, clamped to its `minSize` / `maxSize`.
 * - **A handle between neighbours.** Each handle resizes the *fixed* pane next to it (the one
 *   that is not the flexible pane), so in a three-pane layout the left handle sizes the left
 *   pane and the right handle the right pane.
 * - **Mouse and keyboard.** A handle is a focusable `role="separator"` (the WAI-ARIA window
 *   splitter pattern): drag it, or focus it and press ←/→ (16 px; with Shift 64 px), Home
 *   (the minimum) or End (the maximum). Enter collapses or restores a `collapsible` pane, and
 *   dragging a collapsible pane below half its minimum collapses it. Double-clicking a handle
 *   puts the pane back to its default width.
 * - **Persisted size.** With `storageKey`, the chosen widths and collapsed panes are kept in
 *   `localStorage` (under `apiome:split-pane:<key>`) and restored on the next visit. Storage
 *   that is unavailable or holds junk is ignored, never thrown.
 * - **Children keep their identity.** Resizing only changes the grid's column template, so a
 *   pane's content — an `<iframe>` in particular — is never remounted or reloaded. While a
 *   handle is dragged the pointer is captured by the handle and iframes stop taking pointer
 *   events, so dragging across a preview does not lose the handle.
 * - **Narrow containers stack.** Below a 40 rem (640 px) wide container the panes stack in
 *   one column and the handles hide (a container query in `globals.css`, "SPLIT PANE
 *   (SUX-3.4)"), so the layout still reflows at 320 px.
 *
 * ```tsx
 * <SplitPane
 *   aria-label="Theme editor"
 *   storageKey="slate-theme"
 *   panes={[
 *     { id: 'form', label: 'Form', defaultSize: 360, minSize: 280, maxSize: 520 },
 *     { id: 'preview', label: 'Preview' },
 *   ]}
 * >
 *   <ThemeForm />
 *   <Preview />
 * </SplitPane>
 * ```
 */

/** One pane of a {@link SplitPane}. */
export interface SplitPaneConfig {
  /** A stable id, unique in the split pane. It keys the persisted size. */
  id: string;
  /** The pane's name, used for its handle's accessible name ("Resize Form"). */
  label: string;
  /**
   * The starting width in px. Leave it out on exactly one pane: that pane is the flexible one
   * and takes the remaining width.
   */
  defaultSize?: number;
  /** The narrowest the pane can be dragged, in px. Default 120. */
  minSize?: number;
  /** The widest the pane can be dragged, in px. Default 960. */
  maxSize?: number;
  /** Whether the pane can be collapsed to nothing (Enter on its handle, or dragging it small). */
  collapsible?: boolean;
}

/** The sizes the split pane holds: a width per fixed pane and a collapsed flag. */
export interface SplitPaneLayout {
  /** Width in px of each fixed pane, by pane id. */
  sizes: Record<string, number>;
  /** Pane ids that are collapsed. */
  collapsed: Record<string, boolean>;
}

export interface SplitPaneProps
  extends Omit<React.HTMLAttributes<HTMLDivElement>, 'children' | 'onChange'> {
  /** The panes, left to right: two or three, exactly one without a `defaultSize`. */
  panes: SplitPaneConfig[];
  /** One child per pane, in the same order. */
  children: React.ReactNode;
  /**
   * Persist the layout in `localStorage` under `apiome:split-pane:<storageKey>`. Use one key
   * per page so each page keeps its own width.
   */
  storageKey?: string;
  /** Called after every change of a width or a collapsed flag. */
  onLayoutChange?: (layout: SplitPaneLayout) => void;
  /** Class names for each pane's wrapper, by pane id. */
  paneClassNames?: Record<string, string>;
}

/** Default minimum and maximum pane width, in px. */
export const SPLIT_PANE_DEFAULT_MIN = 120;
export const SPLIT_PANE_DEFAULT_MAX = 960;
/** Keyboard steps, in px: an arrow key, and an arrow key with Shift. */
export const SPLIT_PANE_STEP = 16;
export const SPLIT_PANE_STEP_LARGE = 64;
/** The `localStorage` key prefix for persisted layouts. */
export const SPLIT_PANE_STORAGE_PREFIX = 'apiome:split-pane:';

/**
 * Check a pane list and return the index of its flexible pane.
 *
 * @param panes The pane list.
 * @returns The index of the one pane without a `defaultSize`.
 * @throws When there are not two or three panes, ids repeat, or there is not exactly one
 *   flexible pane — each is a programming error a caller should see at once.
 */
export function flexPaneIndex(panes: SplitPaneConfig[]): number {
  if (panes.length < 2 || panes.length > 3) {
    throw new Error(`SplitPane takes two or three panes, got ${panes.length}.`);
  }
  if (new Set(panes.map((pane) => pane.id)).size !== panes.length) {
    throw new Error('SplitPane pane ids must be unique.');
  }
  const flexible = panes.flatMap((pane, index) => (pane.defaultSize === undefined ? [index] : []));
  if (flexible.length !== 1) {
    throw new Error('SplitPane needs exactly one pane without a defaultSize (the flexible pane).');
  }
  return flexible[0];
}

/**
 * Clamp a width to a pane's bounds.
 *
 * @param pane The pane.
 * @param size A width in px (any finite number).
 * @returns The width, rounded and kept within `minSize` … `maxSize`.
 */
export function clampPaneSize(pane: SplitPaneConfig, size: number): number {
  const min = pane.minSize ?? SPLIT_PANE_DEFAULT_MIN;
  const max = Math.max(min, pane.maxSize ?? SPLIT_PANE_DEFAULT_MAX);
  return Math.round(Math.min(max, Math.max(min, size)));
}

/**
 * The layout a split pane starts with: every fixed pane at its (clamped) default width,
 * nothing collapsed.
 *
 * @param panes The pane list.
 * @returns The default layout.
 */
export function defaultSplitPaneLayout(panes: SplitPaneConfig[]): SplitPaneLayout {
  const sizes: Record<string, number> = {};
  for (const pane of panes) {
    if (pane.defaultSize !== undefined) sizes[pane.id] = clampPaneSize(pane, pane.defaultSize);
  }
  return { sizes, collapsed: {} };
}

/**
 * Merge a stored layout over the defaults, keeping only what still fits the panes: known fixed
 * pane ids, finite widths (clamped), and collapse flags on collapsible panes.
 *
 * @param panes The pane list.
 * @param stored Whatever was parsed from storage (it may be anything).
 * @returns A valid layout.
 */
export function sanitizeSplitPaneLayout(
  panes: SplitPaneConfig[],
  stored: unknown,
): SplitPaneLayout {
  const layout = defaultSplitPaneLayout(panes);
  if (!stored || typeof stored !== 'object') return layout;
  const { sizes, collapsed } = stored as Partial<Record<keyof SplitPaneLayout, unknown>>;
  for (const pane of panes) {
    if (pane.defaultSize === undefined) continue;
    const size = sizes && typeof sizes === 'object' ? (sizes as Record<string, unknown>)[pane.id] : undefined;
    if (typeof size === 'number' && Number.isFinite(size)) {
      layout.sizes[pane.id] = clampPaneSize(pane, size);
    }
    const flag =
      collapsed && typeof collapsed === 'object' ? (collapsed as Record<string, unknown>)[pane.id] : undefined;
    if (pane.collapsible && flag === true) layout.collapsed[pane.id] = true;
  }
  return layout;
}

/**
 * Read a persisted layout.
 *
 * @param storageKey The split pane's key (without the prefix).
 * @param panes The pane list.
 * @returns The stored layout made valid, or the default layout when nothing usable is stored
 *   or storage cannot be read.
 */
export function readSplitPaneLayout(storageKey: string, panes: SplitPaneConfig[]): SplitPaneLayout {
  try {
    const raw = window.localStorage.getItem(SPLIT_PANE_STORAGE_PREFIX + storageKey);
    return sanitizeSplitPaneLayout(panes, raw ? JSON.parse(raw) : null);
  } catch {
    return defaultSplitPaneLayout(panes);
  }
}

/**
 * Persist a layout. Failures (private mode, quota, blocked storage) are ignored.
 *
 * @param storageKey The split pane's key (without the prefix).
 * @param layout The layout to keep.
 */
export function writeSplitPaneLayout(storageKey: string, layout: SplitPaneLayout): void {
  try {
    window.localStorage.setItem(SPLIT_PANE_STORAGE_PREFIX + storageKey, JSON.stringify(layout));
  } catch {
    // Storage is a convenience: the layout still works for this visit.
  }
}

/**
 * The CSS grid column template for a layout: a column per pane (px, `0px` when collapsed, or
 * `minmax(0, 1fr)` for the flexible pane) with an `auto` column for each handle between them.
 *
 * @param panes The pane list.
 * @param layout The current layout.
 * @returns A `grid-template-columns` value.
 */
export function splitPaneColumns(panes: SplitPaneConfig[], layout: SplitPaneLayout): string {
  return panes
    .map((pane) => {
      if (pane.defaultSize === undefined) return 'minmax(0, 1fr)';
      return layout.collapsed[pane.id] ? '0px' : `${layout.sizes[pane.id]}px`;
    })
    .join(' auto ');
}

/**
 * Which pane the handle after pane `handleIndex` resizes, and in which direction.
 *
 * @param handleIndex The handle's index: 0 sits between panes 0 and 1, 1 between 1 and 2.
 * @param flexIndex The flexible pane's index.
 * @returns The index of the pane it sizes, and `1` when moving the handle right grows that
 *   pane (it is left of the handle) or `-1` when it shrinks it (right of the handle).
 */
export function handleTarget(handleIndex: number, flexIndex: number): { index: number; sign: 1 | -1 } {
  return flexIndex > handleIndex ? { index: handleIndex, sign: 1 } : { index: handleIndex + 1, sign: -1 };
}

/**
 * Restore and persist the layout. The first render always uses the defaults (so the server
 * and client markup match); a stored layout is applied in a layout effect before paint.
 *
 * @param panes The pane list.
 * @param storageKey The persistence key, if any.
 * @param onLayoutChange Called after each change.
 * @returns The layout and a setter that persists.
 */
function useSplitPaneLayout(
  panes: SplitPaneConfig[],
  storageKey: string | undefined,
  onLayoutChange: ((layout: SplitPaneLayout) => void) | undefined,
) {
  const [layout, setLayoutState] = React.useState(() => defaultSplitPaneLayout(panes));
  // The panes as a value, so a caller passing a new array with the same panes each render does
  // not re-read storage (and an inline `panes={[…]}` stays cheap).
  const paneSignature = JSON.stringify(panes);

  React.useLayoutEffect(() => {
    if (storageKey) setLayoutState(readSplitPaneLayout(storageKey, JSON.parse(paneSignature)));
  }, [storageKey, paneSignature]);

  const setLayout = React.useCallback(
    (next: SplitPaneLayout) => {
      setLayoutState(next);
      if (storageKey) writeSplitPaneLayout(storageKey, next);
      onLayoutChange?.(next);
    },
    [storageKey, onLayoutChange],
  );

  return [layout, setLayout] as const;
}

/** Props for {@link SplitPaneHandle}. */
interface SplitPaneHandleProps {
  /** The pane this handle sizes. */
  pane: SplitPaneConfig;
  /** That pane's DOM id, for `aria-controls`. */
  paneDomId: string;
  /** `1` when moving right grows the pane, `-1` when it shrinks it. */
  sign: 1 | -1;
  /** The pane's current width in px (ignoring collapse). */
  size: number;
  /** Whether the pane is collapsed. */
  collapsed: boolean;
  /** Set the pane's width (it is clamped) and whether it is collapsed. */
  onResize: (size: number, collapsed: boolean) => void;
  /** Tell the root a drag started or ended, so iframes stop taking the pointer. */
  onDragChange: (dragging: boolean) => void;
}

/**
 * One drag handle: a focusable vertical separator.
 *
 * @param props See {@link SplitPaneHandleProps}.
 * @returns The handle.
 */
function SplitPaneHandle({ pane, paneDomId, sign, size, collapsed, onResize, onDragChange }: SplitPaneHandleProps) {
  const drag = React.useRef<{ pointerId: number; startX: number; startSize: number } | null>(null);
  const min = pane.minSize ?? SPLIT_PANE_DEFAULT_MIN;
  const max = Math.max(min, pane.maxSize ?? SPLIT_PANE_DEFAULT_MAX);

  /** Apply a raw width from a drag: below half the minimum a collapsible pane collapses. */
  const resizeTo = (raw: number) => {
    if (pane.collapsible && raw < min / 2) onResize(size, true);
    else onResize(clampPaneSize(pane, raw), false);
  };

  const onPointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    event.preventDefault();
    event.currentTarget.focus();
    event.currentTarget.setPointerCapture?.(event.pointerId);
    drag.current = { pointerId: event.pointerId, startX: event.clientX, startSize: collapsed ? 0 : size };
    onDragChange(true);
  };

  const onPointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    const current = drag.current;
    if (!current || current.pointerId !== event.pointerId) return;
    resizeTo(current.startSize + sign * (event.clientX - current.startX));
  };

  const endDrag = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!drag.current || drag.current.pointerId !== event.pointerId) return;
    drag.current = null;
    event.currentTarget.releasePointerCapture?.(event.pointerId);
    onDragChange(false);
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    const step = event.shiftKey ? SPLIT_PANE_STEP_LARGE : SPLIT_PANE_STEP;
    const from = collapsed ? min : size;
    switch (event.key) {
      case 'ArrowLeft':
        onResize(clampPaneSize(pane, from - sign * step), false);
        break;
      case 'ArrowRight':
        onResize(clampPaneSize(pane, from + sign * step), false);
        break;
      case 'Home':
        onResize(min, false);
        break;
      case 'End':
        onResize(max, false);
        break;
      case 'Enter':
        if (!pane.collapsible) return;
        onResize(size, !collapsed);
        break;
      default:
        return;
    }
    event.preventDefault();
  };

  return (
    <div
      role="separator"
      tabIndex={0}
      aria-orientation="vertical"
      aria-label={`Resize ${pane.label}`}
      aria-controls={paneDomId}
      aria-valuemin={pane.collapsible ? 0 : min}
      aria-valuemax={max}
      aria-valuenow={collapsed ? 0 : size}
      aria-valuetext={collapsed ? `${pane.label} collapsed` : `${pane.label} ${size} pixels`}
      data-collapsed={collapsed || undefined}
      className="hive-split-pane__handle"
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
      onKeyDown={onKeyDown}
      onDoubleClick={() => onResize(clampPaneSize(pane, pane.defaultSize ?? size), false)}
    />
  );
}

/**
 * The split pane. See the module comment for the behaviour.
 *
 * @param props See {@link SplitPaneProps}.
 * @returns The panes with handles between them.
 */
const SplitPane = React.forwardRef<HTMLDivElement, SplitPaneProps>(function SplitPane(
  { panes, children, storageKey, onLayoutChange, paneClassNames, className, style, ...rest },
  ref,
) {
  const flexIndex = flexPaneIndex(panes);
  const [layout, setLayout] = useSplitPaneLayout(panes, storageKey, onLayoutChange);
  const [dragging, setDragging] = React.useState(false);
  const baseId = React.useId();
  const items = React.Children.toArray(children);
  if (items.length !== panes.length) {
    throw new Error(`SplitPane has ${panes.length} panes but ${items.length} children.`);
  }

  const columns = splitPaneColumns(panes, layout);

  return (
    <div ref={ref} className={cn('hive-split-pane', className)} style={style} {...rest}>
      <div
        className="hive-split-pane__grid"
        data-dragging={dragging || undefined}
        style={{ '--split-pane-columns': columns } as React.CSSProperties}
      >
        {panes.map((pane, index) => {
          const collapsed = Boolean(layout.collapsed[pane.id]);
          const paneDomId = `${baseId}-${pane.id}`;
          const handle =
            index < panes.length - 1
              ? (() => {
                  const target = handleTarget(index, flexIndex);
                  const sized = panes[target.index];
                  return (
                    <SplitPaneHandle
                      key={`handle-${pane.id}`}
                      pane={sized}
                      paneDomId={`${baseId}-${sized.id}`}
                      sign={target.sign}
                      size={layout.sizes[sized.id]}
                      collapsed={Boolean(layout.collapsed[sized.id])}
                      onDragChange={setDragging}
                      onResize={(size, isCollapsed) =>
                        setLayout({
                          sizes: { ...layout.sizes, [sized.id]: size },
                          collapsed: { ...layout.collapsed, [sized.id]: isCollapsed },
                        })
                      }
                    />
                  );
                })()
              : null;
          return (
            <React.Fragment key={pane.id}>
              <div
                id={paneDomId}
                className={cn('hive-split-pane__pane', paneClassNames?.[pane.id])}
                data-pane={pane.id}
                data-collapsed={collapsed || undefined}
                aria-hidden={collapsed || undefined}
                inert={collapsed || undefined}
              >
                {items[index]}
              </div>
              {handle}
            </React.Fragment>
          );
        })}
      </div>
    </div>
  );
});

export { SplitPane };
