'use client';

/**
 * useOverflowEdges — tell a sideways-scrolling strip which of its edges hide content (#7128).
 *
 * A tab strip that scrolls rather than wraps (the Versions main tabs, #6263) clipped its last
 * tab mid-word at 1024 px with nothing to say there was more. This hook measures the strip and
 * writes `data-overflow-start` / `data-overflow-end` onto it; the `.overflow-fade` class in
 * `globals.css` turns each into a fade on that edge, so a cut-off label reads as "scroll for
 * more" rather than as a broken layout.
 *
 * The decision is {@link overflowEdges}, a pure function, so it is testable without layout.
 */

import { useCallback, useEffect, useRef } from 'react';

/** The scroll metrics {@link overflowEdges} reads — a subset of an `HTMLElement`'s. */
export interface OverflowMetrics {
  /** How far the strip is scrolled from its start, in px. */
  scrollLeft: number;
  /** The strip's full content width, in px. */
  scrollWidth: number;
  /** The strip's visible width, in px. */
  clientWidth: number;
}

/** Which edges of a strip hide content. */
export interface OverflowEdges {
  /** Content is hidden before the visible area (the strip is scrolled). */
  start: boolean;
  /** Content is hidden after the visible area. */
  end: boolean;
}

/**
 * A pixel of slack. Browsers report fractional widths rounded differently in `scrollWidth`
 * and `clientWidth`, so a strip that exactly fits can measure one pixel "over".
 */
const EDGE_TOLERANCE_PX = 1;

/**
 * Decide which edges of a strip hide content.
 *
 * @param metrics The strip's scroll metrics.
 * @returns `start` when it is scrolled away from its start, `end` when more lies past its end.
 */
export function overflowEdges({ scrollLeft, scrollWidth, clientWidth }: OverflowMetrics): OverflowEdges {
  // `scrollLeft` is negative in an RTL strip; the distance from the start is its magnitude.
  const scrolled = Math.abs(scrollLeft);
  return {
    start: scrolled > EDGE_TOLERANCE_PX,
    end: scrolled + clientWidth < scrollWidth - EDGE_TOLERANCE_PX,
  };
}

/**
 * Track a strip's hidden edges as it scrolls and resizes.
 *
 * @returns A callback ref for the scrolling element. It keeps the element's
 *   `data-overflow-start` and `data-overflow-end` attributes current; pair it with the
 *   `.overflow-fade` class.
 */
export function useOverflowEdges<T extends HTMLElement>(): (node: T | null) => void {
  const cleanup = useRef<(() => void) | null>(null);

  const ref = useCallback((node: T | null) => {
    cleanup.current?.();
    cleanup.current = null;
    if (!node) return;

    const update = () => {
      const edges = overflowEdges(node);
      node.toggleAttribute('data-overflow-start', edges.start);
      node.toggleAttribute('data-overflow-end', edges.end);
    };
    update();
    node.addEventListener('scroll', update, { passive: true });
    // The window resizes (the strip's own box changes) and tabs appear or disappear (counts
    // load, a feature flag flips — the content changes inside a box of the same width); neither
    // fires a scroll event.
    const resize = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(update);
    resize?.observe(node);
    const mutation =
      typeof MutationObserver === 'undefined' ? null : new MutationObserver(update);
    mutation?.observe(node, { childList: true, subtree: true, characterData: true });
    cleanup.current = () => {
      node.removeEventListener('scroll', update);
      resize?.disconnect();
      mutation?.disconnect();
    };
  }, []);

  useEffect(() => () => cleanup.current?.(), []);

  return ref;
}
