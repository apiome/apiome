/**
 * Shared MCP UI primitives — design tokens & pure presentation helpers (V2-MCP-24.7 / MCAT-10.7).
 *
 * Every MCP catalog screen (browse grid, endpoint detail, lint & score, import flow) reuses the
 * same visual atoms the mockup defines — the A–F grade glyph, the transport / visibility / auth /
 * capability-annotation badges, the health & "last discovered" pills, the MUST/SHOULD finding
 * severity styling, and the detail tab strip. This module holds the *pure*, React-free
 * mappings those primitives render from, so they can be unit-tested directly and so the React
 * components stay free of color/branching literals.
 *
 * Colors are expressed as Tailwind utility classes (the project's token layer, mapped centrally to
 * the brand indigo / slate / emerald / amber / red scales and their `dark:` variants in
 * `globals.css`). Consumers never hard-code a hex or spacing value — they pass a domain value
 * (e.g. a transport string) and receive a {@link McpBadgeTone} + label.
 */

import type { McpLintTier } from './mcpLintUi';

// --- Grade glyph ----------------------------------------------------------------------------
// The A–F glyph is the lead signal on cards, headers, and the lint gauge. Each letter gets a solid
// fill mirroring the mockup's `.g-*` swatches (A emerald, B green, C amber, D orange, F red); an
// unscored endpoint renders a neutral slate glyph.

/** Normalized A–F letter grade (anything unrecognized collapses to `null` → unscored). */
export type McpGradeLetter = 'A' | 'B' | 'C' | 'D' | 'F';

/** Visual styling for one grade glyph: the solid chip fill and the matching on-surface text tint. */
export interface McpGradeGlyphStyle {
  /** A–F, or `null` when the endpoint/version is unscored. */
  letter: McpGradeLetter | null;
  /** Tailwind classes for the solid square chip (background + readable foreground). */
  chipClass: string;
  /** Tailwind text-color class for the letter when drawn over a surface (e.g. the gauge center). */
  textClass: string;
  /** Tailwind `stroke-current` color class for the gauge ring arc. */
  ringClass: string;
}

const GRADE_GLYPH_STYLES: Record<McpGradeLetter, McpGradeGlyphStyle> = {
  A: {
    letter: 'A',
    chipClass: 'bg-emerald-500 text-white',
    textClass: 'text-emerald-600 dark:text-emerald-400',
    ringClass: 'text-emerald-500 dark:text-emerald-400',
  },
  B: {
    letter: 'B',
    chipClass: 'bg-green-500 text-white',
    textClass: 'text-green-600 dark:text-green-400',
    ringClass: 'text-green-500 dark:text-green-400',
  },
  C: {
    letter: 'C',
    chipClass: 'bg-amber-500 text-white',
    textClass: 'text-amber-600 dark:text-amber-400',
    ringClass: 'text-amber-500 dark:text-amber-400',
  },
  D: {
    letter: 'D',
    chipClass: 'bg-orange-500 text-white',
    textClass: 'text-orange-600 dark:text-orange-400',
    ringClass: 'text-orange-500 dark:text-orange-400',
  },
  F: {
    letter: 'F',
    chipClass: 'bg-red-500 text-white',
    textClass: 'text-red-600 dark:text-red-400',
    ringClass: 'text-red-500 dark:text-red-400',
  },
};

/** The neutral glyph used when there is no grade yet. */
const GRADE_GLYPH_UNSCORED: McpGradeGlyphStyle = {
  letter: null,
  chipClass: 'bg-slate-200 text-slate-600 dark:bg-slate-700 dark:text-slate-300',
  textClass: 'text-slate-500 dark:text-slate-400',
  ringClass: 'text-slate-300 dark:text-slate-600',
};

/** Coerce an arbitrary grade value to a known A–F letter, or `null` when unrecognized/empty. */
export function mcpNormalizeGrade(grade: string | null | undefined): McpGradeLetter | null {
  if (typeof grade !== 'string') return null;
  const upper = grade.trim().toUpperCase();
  return upper in GRADE_GLYPH_STYLES ? (upper as McpGradeLetter) : null;
}

/** Resolve the glyph styling for a grade letter (defensively normalized); unscored → neutral. */
export function mcpGradeGlyphStyle(grade: string | null | undefined): McpGradeGlyphStyle {
  const letter = mcpNormalizeGrade(grade);
  return letter ? GRADE_GLYPH_STYLES[letter] : GRADE_GLYPH_UNSCORED;
}

// --- Badge tones ----------------------------------------------------------------------------
// The mockup's `.badge.*` palette: a soft tinted fill + matching text + hairline border, in seven
// semantic tones. McpBadge renders any tone; the resolvers below map a domain value (transport,
// visibility, auth scheme, capability annotation) to the tone + label the mockup specifies.

/** The seven semantic badge tones the MCP surface uses (mirrors the mockup `.badge.*` classes). */
export type McpBadgeTone = 'indigo' | 'green' | 'amber' | 'red' | 'blue' | 'slate' | 'violet';

/** A resolved badge: the tone to paint it and the human label to show. */
export interface McpBadgeSpec {
  tone: McpBadgeTone;
  label: string;
}

/**
 * Resolve an endpoint's transport to a badge. Both the modern `streamable_http` and the legacy
 * `http+sse` transports render as neutral slate chips; the legacy one is labelled as such so it
 * reads as deprecated, matching the mockup.
 */
export function mcpTransportBadge(transport: string | null | undefined): McpBadgeSpec {
  const value = (transport ?? '').trim().toLowerCase();
  if (value === 'streamable_http' || value === 'streamable-http' || value === 'streamablehttp') {
    return { tone: 'slate', label: 'streamable_http' };
  }
  if (
    value === 'http+sse' ||
    value === 'http_sse' ||
    value === 'sse' ||
    value === 'legacy' ||
    value === 'http+sse (legacy)'
  ) {
    return { tone: 'slate', label: 'http+sse (legacy)' };
  }
  return { tone: 'slate', label: transport && transport.trim() ? transport : 'unknown transport' };
}

/** Resolve an endpoint's visibility to a badge: private → indigo, public → green. */
export function mcpVisibilityBadge(visibility: string | null | undefined): McpBadgeSpec {
  const value = (visibility ?? '').trim().toLowerCase();
  if (value === 'public') return { tone: 'green', label: 'Public' };
  if (value === 'private') return { tone: 'indigo', label: 'Private' };
  return { tone: 'slate', label: visibility && visibility.trim() ? visibility : 'Unknown' };
}

/**
 * Resolve an auth scheme to a badge: bearer / header token auth → green, OAuth 2.1 → violet, and
 * an explicit "none" → neutral slate.
 */
export function mcpAuthBadge(scheme: string | null | undefined): McpBadgeSpec {
  const value = (scheme ?? '').trim().toLowerCase();
  if (value === 'bearer') return { tone: 'green', label: 'bearer' };
  if (value === 'header') return { tone: 'green', label: 'header' };
  if (value === 'oauth' || value === 'oauth2' || value === 'oauth_2_1' || value === 'oauth 2.1') {
    return { tone: 'violet', label: 'OAuth 2.1' };
  }
  if (value === 'none' || value === '') return { tone: 'slate', label: 'No auth' };
  return { tone: 'slate', label: scheme as string };
}

/**
 * The MCP tool behavioural annotations, in spec order, with the tone + label the mockup shows when
 * the hint is asserted: readOnly → green, idempotent → blue, destructive → red, openWorld → amber.
 */
const CAPABILITY_ANNOTATION_BADGES: Record<string, McpBadgeSpec> = {
  readOnlyHint: { tone: 'green', label: 'readOnly' },
  idempotentHint: { tone: 'blue', label: 'idempotent' },
  destructiveHint: { tone: 'red', label: 'destructive' },
  openWorldHint: { tone: 'amber', label: 'openWorld' },
};

/** Spec order for the capability-annotation badges, so a card renders them predictably. */
export const MCP_CAPABILITY_ANNOTATION_ORDER: readonly string[] = [
  'readOnlyHint',
  'idempotentHint',
  'destructiveHint',
  'openWorldHint',
] as const;

/**
 * Resolve one capability annotation hint to a badge, or `null` when the hint key is unknown. Only
 * *asserted* (true) hints get a badge — a `false` hint means "this behaviour does not apply" and so
 * is not surfaced, matching the mockup which only shows the chips that are on.
 */
export function mcpCapabilityAnnotationBadge(
  hintKey: string,
  value: boolean,
): McpBadgeSpec | null {
  if (!value) return null;
  return CAPABILITY_ANNOTATION_BADGES[hintKey] ?? null;
}

// --- Health pill ----------------------------------------------------------------------------
// An endpoint's reachability, distilled from its last discovery status into three signal states
// (plus an "unknown" fallback before the first discovery). The dot color follows the mockup's
// `.dot.ok/.warn/.err` swatches.

/** Endpoint health signal states, strongest (healthy) to weakest (unreachable). */
export type McpHealthStatus = 'healthy' | 'degraded' | 'unreachable' | 'unknown';

/** Visual + label metadata for one health state. */
export interface McpHealthMeta {
  status: McpHealthStatus;
  label: string;
  /** Tailwind background class for the status dot. */
  dotClass: string;
  /** Tailwind text class for the accompanying label. */
  textClass: string;
}

const HEALTH_META: Record<McpHealthStatus, McpHealthMeta> = {
  healthy: {
    status: 'healthy',
    label: 'Healthy',
    dotClass: 'bg-emerald-500',
    textClass: 'text-emerald-700 dark:text-emerald-300',
  },
  degraded: {
    status: 'degraded',
    label: 'Degraded',
    dotClass: 'bg-amber-500',
    textClass: 'text-amber-700 dark:text-amber-300',
  },
  unreachable: {
    status: 'unreachable',
    label: 'Unreachable',
    dotClass: 'bg-red-500',
    textClass: 'text-red-700 dark:text-red-300',
  },
  unknown: {
    status: 'unknown',
    label: 'Unknown',
    dotClass: 'bg-slate-400',
    textClass: 'text-slate-600 dark:text-slate-400',
  },
};

/** Resolve the display metadata for a health status. */
export function mcpHealthMeta(status: McpHealthStatus): McpHealthMeta {
  return HEALTH_META[status];
}

/**
 * Map a raw discovery status (as recorded on the endpoint) to a {@link McpHealthStatus}.
 *
 * Successful discovery runs stamp `changed` (new version) or `unchanged` (same surface fingerprint)
 * — both mean the server was reached. Absent/blank statuses — an endpoint not yet discovered —
 * resolve to `unknown`; anything unrecognized is treated conservatively as `unreachable`.
 */
export function mcpHealthFromDiscoveryStatus(status: string | null | undefined): McpHealthStatus {
  const value = (status ?? '').trim().toLowerCase();
  if (!value) return 'unknown';
  // Success outcomes from the discovery engine / sweep (`changed` / `unchanged`) plus legacy aliases.
  if (
    [
      'ok',
      'success',
      'succeeded',
      'healthy',
      'reachable',
      'complete',
      'completed',
      'changed',
      'unchanged',
    ].includes(value)
  ) {
    return 'healthy';
  }
  if (['degraded', 'partial', 'partial_page', 'warning', 'warn', 'stale'].includes(value)) {
    return 'degraded';
  }
  if (
    [
      'error',
      'failed',
      'failure',
      'unreachable',
      'timeout',
      'timed_out',
      'connect_timeout',
      'connect_error',
      'tls_error',
      'refused',
    ].includes(value)
  ) {
    return 'unreachable';
  }
  // Specific discovery error codes (auth_required, rate_limited, protocol_error, …) are still
  // failures to reach a usable surface — treat them as unreachable rather than inventing new pills.
  return 'unreachable';
}

// --- Recency --------------------------------------------------------------------------------
// "Last discovered …" recency, rendered as a compact relative span (just now / 5m / 2h / 3d), and
// falling back to an absolute date for anything older than ~30 days or when the timestamp is
// unparseable. `nowMs` is injected so the formatting is deterministic under test.

const MINUTE_MS = 60_000;
const HOUR_MS = 60 * MINUTE_MS;
const DAY_MS = 24 * HOUR_MS;

/**
 * Format an ISO timestamp as a short relative recency string, given the current time in ms.
 *
 * @param iso   The ISO-8601 instant to describe, or `null`/invalid.
 * @param nowMs The current time in epoch ms (injected for deterministic tests). Defaults to the
 *              wall clock; the default lives here, in a plain module function, so React components
 *              never read the clock during render (which the React-compiler purity rule forbids).
 * @returns `never` when absent/unparseable, otherwise `just now` / `5m ago` / `2h ago` / `3d ago`,
 *          or a locale date string for instants more than ~30 days old.
 */
export function mcpRelativeTime(iso: string | null | undefined, nowMs: number = Date.now()): string {
  if (!iso) return 'never';
  const ms = Date.parse(iso);
  if (Number.isNaN(ms)) return 'never';
  const diff = nowMs - ms;
  if (diff < MINUTE_MS) return 'just now';
  if (diff < HOUR_MS) return `${Math.floor(diff / MINUTE_MS)}m ago`;
  if (diff < DAY_MS) return `${Math.floor(diff / HOUR_MS)}h ago`;
  if (diff < 30 * DAY_MS) return `${Math.floor(diff / DAY_MS)}d ago`;
  return new Date(ms).toLocaleDateString();
}

// --- Finding severity -----------------------------------------------------------------------
// The MUST vs SHOULD split is the lint surface's headline. The tier metadata itself lives in
// `mcpLintUi` (so it stays the single source of truth shared with the lint helpers); here we only
// add the human one-word severity label used by the <FindingSeverity> chip.

/** Short, human label for a requirement tier (`MUST` / `SHOULD` / `Advisory`). */
export const MCP_LINT_TIER_LABEL: Record<McpLintTier, string> = {
  must: 'MUST',
  should: 'SHOULD',
  advisory: 'Advisory',
};

// --- Detail tabs ----------------------------------------------------------------------------
// The detail tab shell. The constant is the single definition of the tab set + order +
// labels; a screen renders the full set or any subset it has content for.

/** One tab in the endpoint detail shell. */
export interface McpDetailTab {
  /** Stable value used as the Radix tab key and content id. */
  value: string;
  /** Human label shown in the tab strip. */
  label: string;
}

/**
 * The canonical MCP endpoint detail strip, in display order (matches the mockup). The `insight` tab
 * (V2-MCP-28.4) sits after Capabilities as the home for the server-profile / evolution / reliability
 * visualizations; a screen renders the full set or any subset it has content for.
 */
export const MCP_DETAIL_TABS: readonly McpDetailTab[] = [
  { value: 'overview', label: 'Overview' },
  { value: 'capabilities', label: 'Capabilities' },
  { value: 'insight', label: 'Insight' },
  { value: 'versions', label: 'Versions' },
  { value: 'lint', label: 'Lint & Score' },
  { value: 'test', label: 'Test' },
  { value: 'credentials', label: 'Credentials' },
  { value: 'settings', label: 'Settings' },
] as const;
