/**
 * Shared class tokens for the Authoring shell (UXE-1.2).
 *
 * Chrome styling lives here rather than inline in each component so the shell,
 * its header, its navigation and every surface placeholder stay visually
 * consistent, and a token change lands everywhere at once. Follows the
 * precedent set by `dashboardScreenClasses.ts`.
 */

import type { AuthoringActionVariant } from '@lib/authoring/actions';
import type { AuthoringStateTone } from '@lib/authoring/state-badges';
import type {
  AuthoringAccent,
  AuthoringDensity,
  AuthoringElevation,
  AuthoringTone,
} from '@lib/authoring/tokens';

/** Full-height column: header, secondary nav, then the scrolling surface. */
export const authoringShellClass = 'flex h-full min-h-0 flex-col bg-white dark:bg-gray-900';

/** Scope header strip. */
export const authoringHeaderClass =
  'flex flex-wrap items-center gap-3 border-b border-gray-200 bg-gradient-to-r from-white via-slate-50 to-white px-4 py-2 dark:border-gray-700 dark:from-gray-800 dark:via-gray-800 dark:to-gray-800';

/** Secondary navigation strip beneath the header. */
export const authoringNavClass =
  'flex items-center gap-1 overflow-x-auto border-b border-gray-200 bg-white px-4 dark:border-gray-700 dark:bg-gray-900';

/** One secondary navigation link. */
export const authoringNavItemClass =
  'inline-flex items-center gap-2 whitespace-nowrap border-b-2 border-transparent px-3 py-2 text-sm font-medium text-gray-600 transition-colors hover:text-gray-900 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-500 dark:text-gray-300 dark:hover:text-white';

/** Active secondary navigation link. */
export const authoringNavItemActiveClass =
  'border-indigo-500 text-indigo-700 dark:border-indigo-400 dark:text-indigo-300';

/** Secondary navigation link the viewer is not entitled to. */
export const authoringNavItemLockedClass = 'cursor-not-allowed opacity-60';

/** Scrolling surface region. */
export const authoringMainClass = 'min-h-0 flex-1 overflow-auto bg-slate-50 dark:bg-gray-900';

/** Content column inside a surface. */
export const authoringContentClass = 'mx-auto flex w-full max-w-6xl flex-col gap-6 p-6';

/** Card surface used by panels and placeholders. */
export const authoringPanelClass =
  'rounded-xl border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-800';

/** Scope selector trigger. */
export const authoringSelectTriggerClass =
  'inline-flex min-w-[11rem] items-center gap-2 rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-900 shadow-sm hover:border-indigo-300 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-500 disabled:cursor-not-allowed disabled:opacity-50 dark:border-gray-600 dark:bg-gray-700/50 dark:text-white dark:hover:border-indigo-500/50';

/** Scope selector popover. */
export const authoringSelectContentClass =
  'z-[9999] overflow-hidden rounded-lg border border-gray-200 bg-white shadow-lg dark:border-gray-700 dark:bg-gray-800';

/** One scope selector option. */
export const authoringSelectItemClass =
  'relative flex cursor-pointer select-none items-center rounded-md py-2 pl-8 pr-3 text-sm text-gray-700 outline-none data-[highlighted]:bg-gray-100 data-[state=checked]:bg-indigo-50 dark:text-gray-300 dark:data-[highlighted]:bg-gray-700 dark:data-[state=checked]:bg-indigo-900/30';

/** Command palette trigger button. */
export const authoringCommandTriggerClass =
  'inline-flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-500 shadow-sm hover:border-indigo-300 hover:text-gray-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-500 dark:border-gray-600 dark:bg-gray-700/50 dark:text-gray-400 dark:hover:text-gray-200';

/** Keyboard hint chip inside the command trigger. */
export const authoringKbdClass =
  'rounded border border-gray-300 bg-gray-50 px-1.5 py-0.5 font-mono text-xs text-gray-500 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-400';

/** Palette overlay. */
export const authoringPaletteOverlayClass =
  'fixed inset-0 z-[10000] bg-black/40 backdrop-blur-sm motion-safe:animate-in motion-safe:fade-in';

/** Palette dialog. */
export const authoringPaletteContentClass =
  'fixed left-1/2 top-24 z-[10001] w-[min(40rem,calc(100vw-2rem))] -translate-x-1/2 overflow-hidden rounded-xl border border-gray-200 bg-white shadow-2xl dark:border-gray-700 dark:bg-gray-800';

/** Palette query input. */
export const authoringPaletteInputClass =
  'w-full border-b border-gray-200 bg-transparent px-4 py-3 text-sm text-gray-900 outline-none placeholder:text-gray-400 dark:border-gray-700 dark:text-white';

/** One palette result row. */
export const authoringPaletteItemClass =
  'flex cursor-pointer select-none items-start gap-3 rounded-md px-3 py-2 text-sm text-gray-700 outline-none data-[selected=true]:bg-indigo-50 dark:text-gray-200 dark:data-[selected=true]:bg-indigo-900/30';

/** Contextual search field focused by `/`. */
export const authoringSearchInputClass =
  'w-full rounded-lg border border-gray-200 bg-white py-2 pl-9 pr-3 text-sm text-gray-900 shadow-sm placeholder:text-gray-400 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-500 dark:border-gray-600 dark:bg-gray-700/50 dark:text-white';

/** Base chip shared by every state badge. */
export const authoringBadgeBaseClass =
  'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium';

/**
 * Palette per semantic tone.
 *
 * Tone is a redundant cue only: every badge also renders an icon and a text
 * label, so status never depends on color (WCAG 2.2 AA, roadmap §27.4).
 */
export const authoringBadgeToneClass: Record<AuthoringStateTone, string> = {
  neutral:
    'border-gray-200 bg-gray-50 text-gray-700 dark:border-gray-600 dark:bg-gray-700/50 dark:text-gray-200',
  info: 'border-sky-200 bg-sky-50 text-sky-800 dark:border-sky-700/60 dark:bg-sky-900/20 dark:text-sky-200',
  success:
    'border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-700/60 dark:bg-emerald-900/20 dark:text-emerald-200',
  warning:
    'border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-700/60 dark:bg-amber-900/20 dark:text-amber-200',
  danger:
    'border-rose-200 bg-rose-50 text-rose-800 dark:border-rose-700/60 dark:bg-rose-900/20 dark:text-rose-200',
};

/* ------------------------------------------------------------------------- *
 * Semantic primitive tokens (UXE-1.3)
 *
 * Everything below maps a *meaning* from `@lib/authoring/tokens` to classes.
 * Primitives never name a colour; they name a tone, an accent, a density or an
 * elevation, and this file decides what that looks like. A theme change is
 * therefore one edit here rather than a sweep through twelve components.
 *
 * Each token also carries a stable, non-Tailwind hook class prefixed
 * `authoring-` (e.g. `authoring-surface`, `authoring-tone-danger`). Those hooks
 * are what `globals.css` targets for the explicit high-contrast theme, matching
 * the `.projection-panel` precedent from EFP-3.2 — high contrast is an opt-in
 * `data-theme`, not something inferred from dark mode (§27.1).
 * ------------------------------------------------------------------------- */

/** Foreground/accent colour per tone, for icons, counts and rules. */
export const authoringToneTextClass: Record<AuthoringTone, string> = {
  neutral: 'text-gray-600 dark:text-gray-300',
  info: 'text-sky-700 dark:text-sky-300',
  success: 'text-emerald-700 dark:text-emerald-300',
  warning: 'text-amber-700 dark:text-amber-300',
  danger: 'text-rose-700 dark:text-rose-300',
};

/** Tinted surface per tone, for callouts and summary strips. */
export const authoringToneSurfaceClass: Record<AuthoringTone, string> = {
  neutral: 'border-gray-200 bg-gray-50 dark:border-gray-600 dark:bg-gray-700/40',
  info: 'border-sky-200 bg-sky-50 dark:border-sky-700/60 dark:bg-sky-900/20',
  success: 'border-emerald-200 bg-emerald-50 dark:border-emerald-700/60 dark:bg-emerald-900/20',
  warning: 'border-amber-200 bg-amber-50 dark:border-amber-700/60 dark:bg-amber-900/20',
  danger: 'border-rose-200 bg-rose-50 dark:border-rose-700/60 dark:bg-rose-900/20',
};

/** Stable hook class per tone, targeted by the high-contrast theme. */
export const authoringToneHookClass: Record<AuthoringTone, string> = {
  neutral: 'authoring-tone authoring-tone-neutral',
  info: 'authoring-tone authoring-tone-info',
  success: 'authoring-tone authoring-tone-success',
  warning: 'authoring-tone authoring-tone-warning',
  danger: 'authoring-tone authoring-tone-danger',
};

/**
 * Restrained product accent (§27.1).
 *
 * Violet is Scribe and cyan is Slate. These identify ownership only; a status
 * never uses them, which is why there is no `success`/`danger` entry here.
 */
export const authoringAccentClass: Record<AuthoringAccent, string> = {
  none: '',
  scribe: 'authoring-accent-scribe text-violet-700 dark:text-violet-300',
  slate: 'authoring-accent-slate text-cyan-700 dark:text-cyan-300',
};

/** Left identity rule used to mark a panel's owning product. */
export const authoringAccentRuleClass: Record<AuthoringAccent, string> = {
  none: '',
  scribe: 'border-l-2 border-l-violet-400 dark:border-l-violet-500',
  slate: 'border-l-2 border-l-cyan-400 dark:border-l-cyan-500',
};

/** Padding rhythm per density. Follows the 4/8px scale from §27.1. */
export const authoringDensityClass: Record<AuthoringDensity, string> = {
  comfortable: 'p-4 text-sm',
  compact: 'px-3 py-2 text-xs',
};

/** Shadow per elevation. Overlays stay low-elevation (§27.1). */
export const authoringElevationClass: Record<AuthoringElevation, string> = {
  flat: '',
  raised: 'shadow-sm',
  overlay: 'shadow-lg',
};

/**
 * Motion utilities for the 120–180ms band (§27.3).
 *
 * `motion-safe:` rather than a bare `transition-*`, so `prefers-reduced-motion`
 * removes the movement without any component opting in individually.
 */
export const authoringMotionClass = {
  /** Selection and hover changes. */
  quick: 'motion-safe:transition-colors motion-safe:duration-[120ms]',
  /** Drawers and inspectors. */
  standard: 'motion-safe:transition-all motion-safe:duration-[160ms] motion-safe:ease-out',
  /** Release progression and chart updates. */
  deliberate: 'motion-safe:transition-all motion-safe:duration-[180ms] motion-safe:ease-out',
} as const;

/** Card surface for a primitive. Composes with tone, accent and elevation. */
export const authoringSurfaceClass =
  'authoring-surface rounded-xl border border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800';

/** Section heading inside a primitive. */
export const authoringSectionTitleClass =
  'text-sm font-semibold text-gray-900 dark:text-white';

/** Supporting copy inside a primitive. */
export const authoringMutedTextClass = 'text-sm text-gray-600 dark:text-gray-300';

/** Monospace treatment for routes, digests, versions and timings (§27.1). */
export const authoringMonoClass = 'font-mono text-xs text-gray-700 dark:text-gray-300';

/** Focus treatment shared by every interactive primitive. */
export const authoringFocusClass =
  'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-500';

/**
 * Button treatment per variant.
 *
 * The 44px-wide/36px-tall minimum keeps every action clear of the 24×24 CSS
 * pixel target-size floor in WCAG 2.2 SC 2.5.8 with spacing to spare (§27.4).
 */
export const authoringActionClass: Record<AuthoringActionVariant, string> = {
  primary:
    'bg-indigo-600 text-white hover:bg-indigo-500 disabled:bg-indigo-300 dark:disabled:bg-indigo-900',
  secondary:
    'border border-gray-300 bg-white text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:bg-gray-700/50 dark:text-gray-200 dark:hover:bg-gray-700',
  ghost: 'text-gray-600 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-700',
};

/** Base treatment shared by every action button. */
export const authoringActionBaseClass =
  'authoring-action inline-flex min-h-9 items-center justify-center gap-1.5 rounded-lg px-3 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-60';

/** Split workspace grid: primary pane, focus pane, inspector. */
export const authoringSplitClass =
  'authoring-split grid min-h-0 flex-1 grid-cols-1 gap-4 lg:grid-cols-[minmax(14rem,18rem)_minmax(0,1fr)] xl:grid-cols-[minmax(14rem,18rem)_minmax(0,1fr)_minmax(18rem,22rem)]';

/** One pane inside the split workspace. */
export const authoringPaneClass =
  'authoring-pane flex min-h-0 min-w-0 flex-col overflow-hidden rounded-xl border border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800';

/** Pane header strip. */
export const authoringPaneHeaderClass =
  'flex items-center justify-between gap-2 border-b border-gray-200 px-3 py-2 dark:border-gray-700';

/** Scrolling body of a pane. */
export const authoringPaneBodyClass = 'min-h-0 flex-1 overflow-auto p-3';

/** Peek drawer overlay. */
export const authoringDrawerOverlayClass =
  'fixed inset-0 z-[10000] bg-black/40 motion-safe:animate-in motion-safe:fade-in';

/** Peek drawer panel, docked to the inline end. */
export const authoringDrawerClass =
  'authoring-drawer fixed inset-y-0 right-0 z-[10001] flex w-[min(34rem,100vw)] flex-col border-l border-gray-200 bg-white shadow-lg dark:border-gray-700 dark:bg-gray-800';

/** One row in the content tree. */
export const authoringTreeRowClass =
  'authoring-tree-row flex w-full min-h-9 cursor-pointer select-none items-center gap-2 rounded-md px-2 text-left text-sm text-gray-700 outline-none hover:bg-gray-100 dark:text-gray-200 dark:hover:bg-gray-700';

/** The selected content tree row. */
export const authoringTreeRowSelectedClass =
  'authoring-tree-row-selected bg-indigo-50 font-medium text-indigo-900 dark:bg-indigo-900/30 dark:text-indigo-100';

/** Diff line treatment per kind. Paired with a `+`/`-` marker, never colour alone. */
export const authoringDiffLineClass = {
  added:
    'authoring-diff-added bg-emerald-50 text-emerald-900 dark:bg-emerald-900/20 dark:text-emerald-100',
  removed: 'authoring-diff-removed bg-rose-50 text-rose-900 dark:bg-rose-900/20 dark:text-rose-100',
  context: 'authoring-diff-context text-gray-600 dark:text-gray-400',
} as const;

/** Progress track. */
export const authoringProgressTrackClass =
  'authoring-progress-track h-1.5 w-full overflow-hidden rounded-full bg-gray-200 dark:bg-gray-700';

/** Progress fill. Width is set inline from the computed percentage. */
export const authoringProgressFillClass =
  'authoring-progress-fill h-full rounded-full bg-indigo-500 motion-safe:transition-[width] motion-safe:duration-[180ms]';
