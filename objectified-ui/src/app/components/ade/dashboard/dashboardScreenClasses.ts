/** Shared layout tokens aligned with the Primitives dashboard screen. */
export const dashboardMainClass = 'flex-1 overflow-y-auto p-6';
export const dashboardContentStackClass = 'space-y-6';

export const dashboardPanelClass =
  'bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700';
export const dashboardPanelPaddedClass = `${dashboardPanelClass} p-4`;

export const dashboardTableWrapClass = `${dashboardPanelClass} overflow-hidden`;

export const dashboardTableTheadClass =
  'bg-gray-50 dark:bg-gray-900 border-b border-gray-200 dark:border-gray-700';

export const dashboardThClass =
  'px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider';

export const dashboardThRightClass =
  'px-6 py-3 text-right text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider';

export const dashboardTbodyClass = 'divide-y divide-gray-200 dark:divide-gray-700';

export const dashboardTrHoverClass =
  'hover:bg-gray-50 dark:hover:bg-gray-900/50 transition-colors';

/**
 * Repositories surface tokens.
 *
 * These belong to the redesigned Repositories list/detail screens. Kept here so
 * Phase B/C pages can import them via the same module the rest of the dashboard
 * already uses.  All names are prefixed `repository*` so they don't collide
 * with the generic dashboard tokens above.
 */
export const repositoryHeaderShellClass =
  'border-b border-gray-200 dark:border-gray-700 bg-gradient-to-r from-indigo-500/10 via-white to-fuchsia-500/5 dark:from-indigo-500/10 dark:via-gray-800 dark:to-fuchsia-500/10';

export const repositoryHeaderIconTileClass =
  'w-10 h-10 rounded-lg flex items-center justify-center bg-gradient-to-br from-indigo-500 to-fuchsia-500 text-white shadow-sm';

export const repositoryHeaderEyebrowClass =
  'text-gray-600 dark:text-gray-400 text-xs mt-1 font-mono';

export const repositoryPanelClass =
  'bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden';

export const repositoryPanelHeaderClass =
  'px-5 py-4 border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900';

export const repositoryPanelEyebrowClass =
  'text-xs text-gray-500 dark:text-gray-400';

export const repositoryMonoCellClass =
  'font-mono text-[11px] text-gray-600 dark:text-gray-300';

export const repositoryStatusChipBaseClass =
  'inline-flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded';

/**
 * Color variants for {@link repositoryStatusChipBaseClass}, keyed by the
 * canonical status returned from the API. Unknown statuses fall back to
 * `neutral`.
 */
export const repositoryStatusChipToneClass = {
  healthy: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300',
  warnings: 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300',
  error: 'bg-rose-100 text-rose-700 dark:bg-rose-900/40 dark:text-rose-300',
  scanning: 'bg-indigo-100 text-indigo-700 dark:bg-indigo-900/40 dark:text-indigo-300',
  disabled: 'bg-slate-200 text-slate-700 dark:bg-slate-700 dark:text-slate-200',
  neutral: 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200',
} as const;

export type RepositoryStatusChipTone = keyof typeof repositoryStatusChipToneClass;

/**
 * Card shell matches the dashboard mockup exactly: white surface, single
 * border, 20px padding, no inner flex direction (children stack via natural
 * block flow + the body row's `flex items-end justify-between`).
 */
export const repositoryKpiCardClass =
  'bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-5';

/**
 * Top-right icon stroke colour. The mockup uses a tone-400 weight so the icon
 * reads as a gentle accent rather than the primary signal — that role is
 * reserved for the value itself ({@link repositoryKpiValueToneClass}).
 */
export const repositoryKpiIconToneClass = {
  indigo: 'text-indigo-400',
  emerald: 'text-emerald-400',
  amber: 'text-amber-400',
  sky: 'text-sky-400',
  violet: 'text-violet-400',
  rose: 'text-rose-400',
  slate: 'text-slate-400',
} as const;

/**
 * Optional tint applied to the headline value. The mockup tints values for
 * "Healthy" (emerald), "Warnings · scanning" (amber), and "Slowest scan"
 * (rose). Other tones leave the value at the default ink colour.
 */
export const repositoryKpiValueToneClass = {
  indigo: '',
  emerald: 'text-emerald-500',
  amber: 'text-amber-500',
  sky: '',
  violet: '',
  rose: 'text-rose-500',
  slate: '',
} as const;

/**
 * Subtitle tone. Defaults to muted gray. Use `warning`/`positive`/`negative`
 * for trend deltas (matches the trending-up/trending-down lines in the
 * mockup).
 */
export const repositoryKpiSubtitleToneClass = {
  default: 'text-gray-500 dark:text-gray-400',
  positive: 'text-emerald-600 dark:text-emerald-400',
  warning: 'text-amber-500 dark:text-amber-400',
  negative: 'text-rose-500 dark:text-rose-400',
} as const;

/**
 * Sparkline stroke colour per tone. Spelled out so Tailwind's JIT picks them
 * up — dynamic `text-${tone}-500` composition would silently fail to ship the
 * matching CSS.
 */
export const repositoryKpiSparkToneClass = {
  indigo: 'text-indigo-500 dark:text-indigo-400',
  emerald: 'text-emerald-500 dark:text-emerald-400',
  amber: 'text-amber-500 dark:text-amber-400',
  sky: 'text-sky-500 dark:text-sky-400',
  violet: 'text-violet-500 dark:text-violet-400',
  rose: 'text-rose-500 dark:text-rose-400',
  slate: 'text-slate-500 dark:text-slate-400',
} as const;

export type RepositoryKpiTone = keyof typeof repositoryKpiIconToneClass;
export type RepositoryKpiSubtitleTone = keyof typeof repositoryKpiSubtitleToneClass;

export const repositoryActivityRowClass =
  'flex items-start gap-3 px-5 py-3 border-b border-gray-100 dark:border-gray-700/60 last:border-b-0';

/**
 * Projects surface tokens.
 *
 * Mirrors the `repository*` set so the redesigned Projects screens can share
 * the same KPI card primitive without inheriting repository-specific labels.
 * Project status tones extend the palette with `inReview` / `draft` /
 * `published` / `deprecated` / `attention` so future API states can chip in
 * without another schema break.
 */
export const projectHeaderShellClass = repositoryHeaderShellClass;
export const projectHeaderIconTileClass =
  'w-10 h-10 rounded-lg flex items-center justify-center bg-gradient-to-br from-indigo-500 to-purple-500 text-white shadow-sm';
export const projectHeaderEyebrowClass = repositoryHeaderEyebrowClass;
export const projectPanelClass = repositoryPanelClass;
export const projectPanelHeaderClass = repositoryPanelHeaderClass;
export const projectMonoCellClass = repositoryMonoCellClass;

export const projectStatusChipBaseClass = repositoryStatusChipBaseClass;

export const projectStatusChipToneClass = {
  enabled: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300',
  disabled: 'bg-slate-200 text-slate-700 dark:bg-slate-700 dark:text-slate-200',
  attention: 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300',
  inReview: 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300',
  draft: 'bg-slate-200 text-slate-700 dark:bg-slate-700 dark:text-slate-200',
  published: 'bg-indigo-100 text-indigo-700 dark:bg-indigo-900/40 dark:text-indigo-300',
  deprecated: 'bg-orange-100 text-orange-700 dark:bg-orange-900/40 dark:text-orange-300',
  deleted: 'bg-rose-100 text-rose-700 dark:bg-rose-900/40 dark:text-rose-300',
  pii: 'bg-rose-100 text-rose-700 dark:bg-rose-900/40 dark:text-rose-300',
  domain: 'bg-violet-100 text-violet-700 dark:bg-violet-900/40 dark:text-violet-300',
  neutral: 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200',
} as const;

export type ProjectStatusChipTone = keyof typeof projectStatusChipToneClass;

/**
 * Project card avatar gradient palette. Picked deterministically from the
 * project id so the same project keeps the same colour across reloads.
 */
export const projectAvatarGradientClasses = [
  'from-indigo-500 to-purple-500',
  'from-emerald-500 to-cyan-500',
  'from-amber-500 to-orange-500',
  'from-rose-500 to-pink-500',
  'from-purple-500 to-fuchsia-500',
  'from-sky-500 to-cyan-500',
  'from-violet-500 to-indigo-500',
  'from-teal-500 to-emerald-500',
] as const;
