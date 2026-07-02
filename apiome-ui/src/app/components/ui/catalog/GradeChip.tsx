'use client';

/**
 * `<GradeChip>` (MFI-24.4, #4084) — the compact `gc-A…F` letter chip for a captured quality grade.
 *
 * Renders a single band letter (A best → F worst) on a solid, band-coloured tile, mirroring the
 * mockup's `gc-A…F` chips (multi-format-import mockup `index.html:198-199`): A emerald, B lime,
 * C amber, D orange, F red. An unrecognised-but-present grade keeps its raw first letter on a
 * neutral slate tile (so nothing is silently dropped); an absent grade shows a slate `–` placeholder.
 *
 * Kept in `ui/catalog/*` alongside the format/protocol pills so it can be shared with the catalog
 * table (this ticket) and the grade surfaces of neighbouring tickets (e.g. MFI-25.5).
 */

import * as React from 'react';
import { cn } from '../../../../../lib/utils';

/** The A–F quality bands the chip colours. */
export type GradeChipLetter = 'A' | 'B' | 'C' | 'D' | 'F';

/**
 * Per-band solid background tone, mirroring the mockup's `gc-A…F` colours: A emerald, B lime,
 * C amber, D orange, F red. Exported so grade surfaces elsewhere can share the same band palette.
 */
export const GRADE_CHIP_TONE_CLASS: Record<GradeChipLetter, string> = {
  A: 'bg-emerald-500',
  B: 'bg-lime-500',
  C: 'bg-amber-500',
  D: 'bg-orange-500',
  F: 'bg-red-500',
};

const CHIP_BASE = 'inline-grid h-6 w-6 place-items-center rounded-md text-xs font-bold leading-none';

/**
 * Normalise a raw grade token to one of the A–F band letters, or `null` when it is not a recognised
 * band. Uses the uppercased first character, so `A+` / `a` → `A`.
 */
export function normalizeGradeLetter(grade: string | null | undefined): GradeChipLetter | null {
  if (!grade || !grade.trim()) return null;
  const c = grade.trim().charAt(0).toUpperCase();
  return c === 'A' || c === 'B' || c === 'C' || c === 'D' || c === 'F' ? c : null;
}

export interface GradeChipProps extends React.HTMLAttributes<HTMLSpanElement> {
  /** The raw grade token off the catalog item (a letter, or a fuller grade like `A-`). */
  grade: string | null | undefined;
}

/**
 * Render the grade chip. A recognised band letter gets its solid band colour; a present-but-unknown
 * grade keeps its raw first letter on a neutral slate tile; an absent grade renders a slate `–`.
 */
export const GradeChip = React.forwardRef<HTMLSpanElement, GradeChipProps>(
  ({ grade, className, ...props }, ref) => {
    const letter = normalizeGradeLetter(grade);
    const hasGrade = Boolean(grade && grade.trim());
    const display = hasGrade ? grade!.trim().charAt(0).toUpperCase() : '–';
    const tone = letter
      ? `${GRADE_CHIP_TONE_CLASS[letter]} text-white`
      : 'bg-slate-300 text-slate-600 dark:bg-slate-600 dark:text-slate-200';

    return (
      <span
        ref={ref}
        className={cn(CHIP_BASE, tone, className)}
        title={hasGrade ? `Grade ${display}` : 'No grade captured yet'}
        data-testid="grade-chip"
        {...props}
      >
        {display}
      </span>
    );
  },
);
GradeChip.displayName = 'GradeChip';
