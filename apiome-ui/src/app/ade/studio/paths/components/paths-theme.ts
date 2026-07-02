/**
 * Paths-specific design tokens. Extends the canonical {@link sidebarTheme}
 * with surfaces and accents used across the Paths section (properties
 * panels, canvas chrome, palette, nodes).
 *
 * The goal is a single source of truth so every redesign sweep flows
 * through this file instead of inline hex codes and gradients.
 */
import { sidebarTheme } from '../../../../components/sidebar/sidebar-theme';

/** Standard width of a right-side properties panel (matches sidebar width). */
export const PROPERTIES_PANEL_WIDTH_PX = 360;

/** Node width range used by request/response body nodes on the canvas. */
export const NODE_BODY_MIN_WIDTH_PX = 320;
export const NODE_BODY_MAX_WIDTH_PX = 400;

/** Node width range used by smaller attachment nodes (class, response stub). */
export const NODE_ATTACH_MIN_WIDTH_PX = 220;
export const NODE_ATTACH_MAX_WIDTH_PX = 300;

/** Standard height of a node header so every node aligns visually. */
export const NODE_HEADER_HEIGHT_PX = 32;

/**
 * HTTP method color map. These feed both node accents and palette chips.
 * Kept in one place so a theme change does not require touching 6+ files.
 * Values match {@link OPERATION_COLORS} in `paths-operation-colors.ts`,
 * but re-exported here so consumers import a single theme surface.
 */
export { OPERATION_COLORS as METHOD_COLORS } from './paths-operation-colors';

/**
 * Resolve an HTTP status code to a semantic role. Used by node accents,
 * status chips, and section headers in the response editor.
 */
export type StatusRole = 'informational' | 'success' | 'redirect' | 'client-error' | 'server-error' | 'default';

export function statusRoleForCode(code: string): StatusRole {
  const n = Number.parseInt(code, 10);
  if (Number.isNaN(n)) return 'default';
  if (n >= 100 && n < 200) return 'informational';
  if (n >= 200 && n < 300) return 'success';
  if (n >= 300 && n < 400) return 'redirect';
  if (n >= 400 && n < 500) return 'client-error';
  if (n >= 500 && n < 600) return 'server-error';
  return 'default';
}

/**
 * Tailwind class fragments for status role chips. Colors are semantic
 * (emerald/amber/rose) and used *only* for status badges, not for chrome.
 */
export const STATUS_ROLE_CHIP: Record<StatusRole, string> = {
  informational:
    'bg-slate-100 text-slate-700 dark:bg-slate-800/70 dark:text-slate-300 ring-1 ring-inset ring-slate-200 dark:ring-slate-700',
  success:
    'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300 ring-1 ring-inset ring-emerald-200 dark:ring-emerald-900/60',
  redirect:
    'bg-sky-50 text-sky-700 dark:bg-sky-950/40 dark:text-sky-300 ring-1 ring-inset ring-sky-200 dark:ring-sky-900/60',
  'client-error':
    'bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300 ring-1 ring-inset ring-amber-200 dark:ring-amber-900/60',
  'server-error':
    'bg-rose-50 text-rose-700 dark:bg-rose-950/40 dark:text-rose-300 ring-1 ring-inset ring-rose-200 dark:ring-rose-900/60',
  default:
    'bg-slate-100 text-slate-700 dark:bg-slate-800/70 dark:text-slate-300 ring-1 ring-inset ring-slate-200 dark:ring-slate-700',
};

/**
 * Parameter location chips. Replaces the hex-coded backgrounds scattered
 * across the operation and parameter panels.
 */
export type ParameterLocation = 'path' | 'query' | 'header' | 'cookie';

export const PARAM_LOCATION_CHIP: Record<ParameterLocation, string> = {
  path:
    'bg-indigo-50 text-indigo-700 dark:bg-indigo-950/40 dark:text-indigo-300 ring-1 ring-inset ring-indigo-200 dark:ring-indigo-900/60',
  query:
    'bg-sky-50 text-sky-700 dark:bg-sky-950/40 dark:text-sky-300 ring-1 ring-inset ring-sky-200 dark:ring-sky-900/60',
  header:
    'bg-violet-50 text-violet-700 dark:bg-violet-950/40 dark:text-violet-300 ring-1 ring-inset ring-violet-200 dark:ring-violet-900/60',
  cookie:
    'bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300 ring-1 ring-inset ring-amber-200 dark:ring-amber-900/60',
};

/**
 * Paths-specific surface tokens. Consumers should prefer these over
 * re-deriving Tailwind classes inline so every Paths surface reads from
 * the same palette.
 */
export const pathsTheme = {
  ...sidebarTheme,
  /** Slim dividers inside panels (between sections). */
  divider: 'border-slate-200/70 dark:border-slate-800/70',
  /** Card surface used for section headers and inline lists. */
  cardSurface: 'bg-slate-50/70 dark:bg-slate-900/40',
  /** Danger accent for destructive actions (delete buttons, inline). */
  dangerText: 'text-rose-600 dark:text-rose-400',
  dangerHover: 'hover:bg-rose-50 dark:hover:bg-rose-950/40',
} as const;

export { sidebarTheme };
