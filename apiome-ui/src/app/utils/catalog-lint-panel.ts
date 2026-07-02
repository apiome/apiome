/**
 * Pure presentation helpers for the inline Lint & Score panel (MFI-25.5, #4090).
 *
 * The panel renders a grade gauge, category bars, and a findings list from the server lint report
 * (`GET /api/catalog/{id}/lint`). These helpers are the panel's data-shaping layer, kept pure (no
 * React, no DOM) so the gauge geometry, the category-bar source selection, and the MUST/SHOULD
 * mapping are unit-testable in isolation. The authoritative score/grade always come from the server
 * report — nothing here recomputes them.
 */

import type {
  LintCategoryScore,
  LintSeverity,
  VersionLintFinding,
  VersionLintReport,
} from './version-lint-report';

/** A category's severity tally, used for the fallback bars when real category scores are absent. */
export interface CategorySeverityBreakdown {
  /** The raw category key from the findings (e.g. `documentation`). */
  category: string;
  error: number;
  warning: number;
  info: number;
  /** Total findings in the category (error + warning + info). */
  total: number;
}

/** Clamp any numeric input to an integer in the inclusive 0–100 score range. */
export function clampScore(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.min(100, Math.max(0, Math.round(value)));
}

/**
 * Resolve the per-category rollup scores (MFI-25.6) from a report, or `null` when the enrichment is
 * absent so the caller can fall back to the severity breakdown. Filters out malformed entries and
 * clamps scores into range; returns `null` (not `[]`) when there is nothing usable, so an empty
 * `categories: []` from the server reads the same as "not provided".
 */
export function resolveCategoryScores(
  report: Pick<VersionLintReport, 'categories'> | null | undefined,
): LintCategoryScore[] | null {
  const raw = report?.categories;
  if (!Array.isArray(raw)) return null;
  const scores = raw
    .filter(
      (c): c is LintCategoryScore =>
        !!c && typeof c.name === 'string' && c.name.trim() !== '' && Number.isFinite(c.score),
    )
    .map((c) => ({ name: c.name, score: clampScore(c.score) }));
  return scores.length > 0 ? scores : null;
}

/** Severity weight for ordering (higher = more severe), matching the findings sort. */
const SEVERITY_WEIGHT: Record<string, number> = { error: 100, warning: 10, info: 1 };

/**
 * Group findings by category into severity tallies, ordered by severity weight (categories with
 * errors first, then warnings, then info), breaking ties alphabetically. This is the graceful
 * fallback for the category bars until real per-category scores (MFI-25.6) are available: it renders
 * the shape of the problem (which categories carry the most severe findings) without inventing a
 * 0–100 score the server has not computed.
 */
export function deriveCategorySeverityBreakdown(
  findings: readonly VersionLintFinding[],
): CategorySeverityBreakdown[] {
  const byCategory = new Map<string, CategorySeverityBreakdown>();
  for (const f of findings) {
    const key = (f.category || 'other').trim() || 'other';
    let row = byCategory.get(key);
    if (!row) {
      row = { category: key, error: 0, warning: 0, info: 0, total: 0 };
      byCategory.set(key, row);
    }
    if (f.severity === 'error' || f.severity === 'warning' || f.severity === 'info') {
      row[f.severity] += 1;
    }
    row.total += 1;
  }
  return [...byCategory.values()].sort((a, b) => {
    const wa = a.error * SEVERITY_WEIGHT.error + a.warning * SEVERITY_WEIGHT.warning + a.info;
    const wb = b.error * SEVERITY_WEIGHT.error + b.warning * SEVERITY_WEIGHT.warning + b.info;
    if (wa !== wb) return wb - wa;
    return a.category.localeCompare(b.category);
  });
}

/**
 * The conformance strength a finding's severity implies, mirroring the mockup's MUST/SHOULD chip:
 * an `error` is a MUST (a hard requirement violated); a `warning`/`info` is a SHOULD (a
 * recommendation). Derived from severity because the report has no separate MUST/SHOULD field.
 */
export function mustLabelForSeverity(severity: LintSeverity | string): 'MUST' | 'SHOULD' {
  return severity === 'error' ? 'MUST' : 'SHOULD';
}

/**
 * Humanize a category key for a bar label: `api-design` / `api_design` → `Api design`. Kept simple
 * (sentence case on the first token) so it degrades cleanly for unknown categories.
 */
export function humanizeCategory(category: string): string {
  const spaced = category.replace(/[-_]+/g, ' ').trim();
  if (!spaced) return 'Other';
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/**
 * The `stroke-dashoffset` for an SVG progress ring so that `score`% of the circumference is drawn.
 * A score of 100 fills the ring (offset 0); 0 leaves it empty (offset = circumference). The input is
 * clamped so out-of-range scores never over/under-draw the arc.
 */
export function gaugeDashOffset(score: number, circumference: number): number {
  const pct = clampScore(score) / 100;
  return circumference * (1 - pct);
}

// --- Requirement tiers (MFI-28.2) -----------------------------------------------------------
// The MCP "Lint & Score" tab groups findings into MUST / SHOULD / advisory sections; MFI-28.2
// brings the catalog panel to parity. A finding's severity maps to a requirement tier — an
// `error` is a hard requirement (MUST), a `warning` a recommendation (SHOULD), and `info` an
// advisory note — mirroring `mcpLintUi`'s `MCP_LINT_SEVERITY_TIER` so both surfaces speak one
// visual language.

/** The three requirement tiers a finding can fall into, strongest first. */
export type CatalogLintTier = 'must' | 'should' | 'advisory';

/** Map a finding severity to its requirement tier (defaults to `advisory` for unknown severities). */
const SEVERITY_TIER: Record<string, CatalogLintTier> = {
  error: 'must',
  warning: 'should',
  info: 'advisory',
};

/** Resolve a finding's requirement tier from its severity. */
export function catalogLintFindingTier(severity: LintSeverity | string): CatalogLintTier {
  return SEVERITY_TIER[severity] ?? 'advisory';
}

/** Display metadata for one requirement tier: headline label, count caption, and row styling. */
export interface CatalogLintTierMeta {
  key: CatalogLintTier;
  /** Headline label rendered on the section header (`MUST` / `SHOULD` / `Advisory`). */
  label: string;
  /** One-line description shown beside the section header. */
  description: string;
  /** Badge (severity chip) CSS classes for the section header count. */
  badgeClass: string;
  /** Left-border + tint CSS classes for a finding row in this tier. */
  rowClass: string;
}

const TIER_META: Record<CatalogLintTier, CatalogLintTierMeta> = {
  must: {
    key: 'must',
    label: 'MUST',
    description: 'Hard requirements — fix these to raise the grade.',
    badgeClass: 'bg-rose-100 text-rose-700 dark:bg-rose-900/40 dark:text-rose-300',
    rowClass:
      'border-l-4 border-rose-500 bg-rose-50/60 dark:border-rose-500 dark:bg-rose-950/20',
  },
  should: {
    key: 'should',
    label: 'SHOULD',
    description: 'Recommendations — address these to polish the surface.',
    badgeClass: 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300',
    rowClass:
      'border-l-4 border-amber-500 bg-amber-50/60 dark:border-amber-500 dark:bg-amber-950/20',
  },
  advisory: {
    key: 'advisory',
    label: 'Advisory',
    description: 'Informational notes about the surface.',
    badgeClass: 'bg-sky-100 text-sky-800 dark:bg-sky-900/40 dark:text-sky-300',
    rowClass:
      'border-l-4 border-gray-300 bg-gray-50/60 dark:border-gray-600 dark:bg-gray-900/30',
  },
};

/** The requirement tiers in display order (strongest first). */
export const CATALOG_LINT_TIER_ORDER: readonly CatalogLintTier[] = [
  'must',
  'should',
  'advisory',
] as const;

/** Resolve the display metadata for a requirement tier. */
export function catalogLintTierMeta(tier: CatalogLintTier): CatalogLintTierMeta {
  return TIER_META[tier];
}

/** Per-tier finding tallies (MUST / SHOULD / advisory). */
export interface CatalogLintTierCounts {
  must: number;
  should: number;
  advisory: number;
}

/**
 * Count findings per requirement tier, derived from the findings themselves so the totals always
 * agree with the sections the panel renders.
 */
export function catalogLintTierCounts(
  findings: readonly VersionLintFinding[],
): CatalogLintTierCounts {
  const counts: CatalogLintTierCounts = { must: 0, should: 0, advisory: 0 };
  for (const f of findings) counts[catalogLintFindingTier(f.severity)] += 1;
  return counts;
}

/** A requirement tier with its (severity-sorted) findings, for sectioned rendering. */
export interface CatalogLintTierGroup {
  meta: CatalogLintTierMeta;
  findings: VersionLintFinding[];
}

/**
 * Group already-sorted findings by requirement tier in display order (MUST → SHOULD → advisory).
 * Every tier is returned (even when empty) so the caller can decide whether to render empty
 * sections; findings within a tier keep their incoming order (the caller sorts most-severe-first).
 */
export function catalogLintGroupByTier(
  findings: readonly VersionLintFinding[],
): CatalogLintTierGroup[] {
  return CATALOG_LINT_TIER_ORDER.map((tier) => ({
    meta: TIER_META[tier],
    findings: findings.filter((f) => catalogLintFindingTier(f.severity) === tier),
  }));
}

// --- Report provenance (MFI-28.2) -----------------------------------------------------------
// The provenance strip mirrors the MCP report header: it tells the reader whether the score they
// see is the one persisted on the version at import time (MFI-4.2) or a fresh live recompute, and
// surfaces the report fingerprint. The catalog `/lint` route always recomputes live and folds in a
// captured score for comparison, so we derive "stored vs computed" from that captured score:
//   - no captured score            → `computed` (this version was never scored at import);
//   - captured score, stale        → `stale`    (persisted score is out of date vs this recompute);
//   - captured score, fresh        → `stored`   (this live report matches the persisted score).

/** Where the displayed score comes from, for the provenance strip's source chip. */
export type CatalogLintSource = 'stored' | 'computed' | 'stale';

/** The provenance summary rendered in the strip: source classification + human label. */
export interface CatalogLintProvenance {
  source: CatalogLintSource;
  /** Human label for the source chip (e.g. "Stored report"). */
  label: string;
  /** True when the persisted score is stale relative to this live report (drives a warning tone). */
  stale: boolean;
}

/** Human labels for each source classification. */
const SOURCE_LABELS: Record<CatalogLintSource, string> = {
  stored: 'Stored report',
  computed: 'Computed live',
  stale: 'Recomputed (stored is stale)',
};

/**
 * Classify a report's provenance from its captured-score fields. `capturedScore == null` means the
 * version was never scored at import, so this is a live computation; a captured score that is stale
 * (`scoreIsStale`) means the persisted score no longer matches this recompute; otherwise the live
 * report agrees with the stored score.
 */
export function catalogLintProvenance(
  report: Pick<VersionLintReport, 'capturedScore' | 'scoreIsStale'>,
): CatalogLintProvenance {
  let source: CatalogLintSource;
  if (report.capturedScore == null) source = 'computed';
  else if (report.scoreIsStale) source = 'stale';
  else source = 'stored';
  return { source, label: SOURCE_LABELS[source], stale: source === 'stale' };
}

// --- Finding → parsed-entity deep links (MFI-28.2) ------------------------------------------
// A finding's `path` addresses where in the reconstructed OpenAPI the rule fired, e.g.
// `components.schemas.Payment` or `components.schemas.Order.properties.total`. The Overview tab
// renders the normalized parsed entities (MFI-25.2/25.3) by `name`. We resolve a finding path back
// to a parsed entity by matching path segments against the known entity names, then address the
// entity by a shared DOM anchor id both producers compute the same way — mirroring
// `mcpCapabilityAnchorId` / `mcpLintFindingTarget`.

/**
 * The shared DOM anchor id for a parsed entity, computed identically by the Overview tab (which
 * renders the anchor) and the Lint tab (which links to it). Non-id-safe characters are collapsed to
 * hyphens so the id is always a valid, stable token.
 */
export function catalogEntityAnchorId(name: string): string {
  const safeName = (name || 'unnamed').replace(/[^A-Za-z0-9_-]+/g, '-');
  return `catalog-entity-${safeName}`;
}

/**
 * Resolve a finding `path` to the parsed entity it flags, or `null` when no entity matches. The path
 * is split on `.` and `/` into segments; the deepest (most specific) segment that names a known
 * entity wins, so `components.schemas.Order.properties.total` resolves to `Order` rather than a
 * shallower container. Matching is exact and case-sensitive, as OpenAPI component names are.
 *
 * @param path The finding's location path.
 * @param entityNames The set of parsed-entity names rendered in the Overview.
 * @returns The matching entity name, or `null` when the finding is not entity-scoped.
 */
export function resolveCatalogFindingEntity(
  path: string,
  entityNames: ReadonlySet<string>,
): string | null {
  if (!path || entityNames.size === 0) return null;
  const segments = path.split(/[./]/).filter(Boolean);
  for (let i = segments.length - 1; i >= 0; i -= 1) {
    if (entityNames.has(segments[i])) return segments[i];
  }
  return null;
}
