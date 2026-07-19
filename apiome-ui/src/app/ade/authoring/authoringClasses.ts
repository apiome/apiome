/**
 * Shared class tokens for the Authoring shell (UXE-1.2).
 *
 * Chrome styling lives here rather than inline in each component so the shell,
 * its header, its navigation and every surface placeholder stay visually
 * consistent, and a token change lands everywhere at once. Follows the
 * precedent set by `dashboardScreenClasses.ts`.
 */

import type { AuthoringStateTone } from '@lib/authoring/state-badges';

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
