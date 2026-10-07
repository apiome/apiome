'use client';

import * as React from 'react';
import { cn } from '../../../../lib/utils';

/**
 * LiveRegion — a visually hidden announcer for status that changes on its own (HIVE-10.2, #5338).
 *
 * `docs/mockups/DESIGN.md` §9: "live regions for save state and async jobs". A screen reader
 * only announces a live region's *changes*, so the region is always rendered (empty until
 * there is something to say) and the caller passes the sentence to speak as `message`. Keep
 * the message coarse — "Import running: step 3 of 8", not every percent tick — so a polling
 * surface does not talk over the reader.
 *
 * - `politeness="polite"` (default) waits for the reader to finish; use it for progress and
 *   save state. `"assertive"` interrupts; reserve it for failures the user must act on.
 * - The region is `aria-atomic`, so the whole sentence is read, not just the changed words.
 *
 * @example
 * <LiveRegion message={saving ? 'Saving…' : dirty ? 'Unsaved changes' : 'Saved'} />
 */
export interface LiveRegionProps extends Omit<React.HTMLAttributes<HTMLDivElement>, 'children' | 'role'> {
  /** The sentence to announce. Empty or `null` renders an empty (silent) region. */
  message: string | null | undefined;
  /** How urgently the reader announces a change. Defaults to `polite`. */
  politeness?: 'polite' | 'assertive';
}

export const LiveRegion = React.forwardRef<HTMLDivElement, LiveRegionProps>(
  ({ message, politeness = 'polite', className, ...props }, ref) => (
    <div
      ref={ref}
      role={politeness === 'assertive' ? 'alert' : 'status'}
      aria-live={politeness}
      aria-atomic="true"
      className={cn('sr-only', className)}
      data-live-region=""
      {...props}
    >
      {message || ''}
    </div>
  ),
);
LiveRegion.displayName = 'LiveRegion';
