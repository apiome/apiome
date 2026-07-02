/**
 * Presentational copy + tone classes for the per-file refresh status chip
 * (RAR-2.3, #3520).
 *
 * The REST read model surfaces `refresh_status` as one of the kebab-case codes
 * below (see apiome-rest `RefreshStatus`). This module is the single place
 * that maps a code to user-facing label + tooltip + tone classes, so the
 * repository file browser and any other surface render the state machine
 * identically. Kept pure (no React) so it is unit-testable in isolation, mirroring
 * `branch-divergence-chip-copy.ts`.
 */

/** Wire codes for the per-file refresh state (must match REST `RefreshStatus`). */
export type RefreshStatusCode =
  | 'up-to-date'
  | 'stale'
  | 'refreshing'
  | 'failed'
  | 'diverged';

export type RefreshStatusTone = RefreshStatusCode;

export interface RefreshStatusPresentation {
  /** Short chip label. */
  label: string;
  /** Longer hover/aria explanation of the state. */
  description: string;
  /** Tone key for class selection. */
  tone: RefreshStatusTone;
}

const PRESENTATION: Record<RefreshStatusCode, Omit<RefreshStatusPresentation, 'tone'>> = {
  'up-to-date': {
    label: 'Up to date',
    description: 'The imported version reflects the latest source commit.',
  },
  stale: {
    label: 'Stale',
    description: 'A newer source commit with changed content is available to import.',
  },
  refreshing: {
    label: 'Refreshing',
    description: 'A refresh is in progress for this file.',
  },
  failed: {
    label: 'Failed',
    description: 'The most recent refresh attempt failed; it will be retried.',
  },
  diverged: {
    label: 'Diverged',
    description:
      'The imported version was edited after import; auto-refresh is held until resolved.',
  },
};

/**
 * Resolve the chip label, description, and tone for a refresh status code.
 * Unknown/missing codes fall back to the neutral up-to-date presentation so the
 * UI never renders a blank chip.
 *
 * @param status The `refresh_status` code from the REST read model.
 * @returns Label, description, and tone for the chip.
 */
export function getRefreshStatusPresentation(
  status: string | null | undefined,
): RefreshStatusPresentation {
  const code = (status ?? '') as RefreshStatusCode;
  const copy = PRESENTATION[code] ?? PRESENTATION['up-to-date'];
  const tone: RefreshStatusTone = (code in PRESENTATION ? code : 'up-to-date');
  return { ...copy, tone };
}

/**
 * Tailwind utility classes for a refresh-status chip, keyed by tone. Mirrors the
 * glass/border styling used by the branch divergence chip so the two read as a
 * family.
 *
 * @param tone The tone returned by {@link getRefreshStatusPresentation}.
 * @returns A class string for the chip element.
 */
export function refreshStatusChipToneClasses(tone: RefreshStatusTone): string {
  const base =
    'inline-flex items-center gap-1 rounded-lg border px-2.5 py-1 text-xs font-medium shadow-sm backdrop-blur-md transition-all focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/30';
  switch (tone) {
    case 'up-to-date':
      return `${base} border-emerald-300/60 bg-emerald-50/50 text-emerald-900 dark:border-emerald-700/45 dark:bg-emerald-950/35 dark:text-emerald-100`;
    case 'stale':
      return `${base} border-amber-300/60 bg-amber-50/50 text-amber-950 dark:border-amber-700/45 dark:bg-amber-950/40 dark:text-amber-100`;
    case 'refreshing':
      return `${base} border-indigo-300/60 bg-indigo-50/50 text-indigo-950 dark:border-indigo-700/45 dark:bg-indigo-950/40 dark:text-indigo-100`;
    case 'failed':
      return `${base} border-rose-300/60 bg-rose-50/50 text-rose-950 dark:border-rose-700/45 dark:bg-rose-950/40 dark:text-rose-100`;
    case 'diverged':
    default:
      return `${base} border-purple-300/60 bg-purple-50/50 text-purple-950 dark:border-purple-700/45 dark:bg-purple-950/40 dark:text-purple-100`;
  }
}
