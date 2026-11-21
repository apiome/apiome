'use client';

import * as React from 'react';

import { cn } from '../../../../lib/utils';

/**
 * ColdRenderNote — what a comparison says while a revision's document is rendered for the first
 * time (COA-5.6, #7082).
 *
 * A diff or compatibility check reads each side's OpenAPI document from the document store. The
 * first read of a revision (or the first read after an edit) renders the document, which takes a
 * while for a large version; every later read is served from the stored copy. A spinner alone
 * looks like a hang during that render, so a wait that outlasts {@link COLD_RENDER_NOTE_DELAY_MS}
 * gains this note. A warm comparison answers before the delay and never shows it.
 *
 * ```tsx
 * <LoadingState message="Comparing with the merge base…" detail={<ColdRenderNote />} />
 * // Outside a LoadingState, the note is its own polite live region:
 * {loading && <ColdRenderNote standalone />}
 * ```
 */

/** How long a wait lasts before the note appears, in milliseconds. */
export const COLD_RENDER_NOTE_DELAY_MS = 2500;

/** The note's sentence. */
export const COLD_RENDER_NOTE_TEXT =
  'Rendering the documents for the first time. A large version takes a while; later comparisons use the stored copy.';

/**
 * Report whether `delayMs` has passed since the calling component mounted.
 *
 * @param delayMs - The delay, in milliseconds.
 * @returns `false` until the delay has passed, then `true`.
 */
export function useDelayElapsed(delayMs: number): boolean {
  const [elapsed, setElapsed] = React.useState(false);
  React.useEffect(() => {
    const timer = window.setTimeout(() => setElapsed(true), Math.max(0, delayMs));
    return () => window.clearTimeout(timer);
  }, [delayMs]);
  return elapsed;
}

export interface ColdRenderNoteProps {
  /** Wait this long before showing the note; defaults to {@link COLD_RENDER_NOTE_DELAY_MS}. */
  delayMs?: number;
  /**
   * Make the note its own `role="status"` region. Leave it off inside a `LoadingState`, which is
   * already a live region (a nested one would announce twice).
   */
  standalone?: boolean;
  /** Extra classes. */
  className?: string;
}

/**
 * The note, shown once the wait has lasted `delayMs`. Mount it only while the wait is running.
 *
 * @param props - See {@link ColdRenderNoteProps}.
 * @returns The note, or `null` before the delay has passed.
 */
export function ColdRenderNote({
  delayMs = COLD_RENDER_NOTE_DELAY_MS,
  standalone = false,
  className,
}: ColdRenderNoteProps) {
  const shown = useDelayElapsed(delayMs);
  if (!shown) return null;
  return (
    <p
      className={cn('cold-render-note', className)}
      role={standalone ? 'status' : undefined}
      aria-live={standalone ? 'polite' : undefined}
      data-testid="cold-render-note"
    >
      {COLD_RENDER_NOTE_TEXT}
    </p>
  );
}
