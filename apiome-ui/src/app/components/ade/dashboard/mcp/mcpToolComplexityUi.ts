/**
 * Tool schema "shape" & complexity presentation helpers (V2-MCP-29.3 / MCAT-15.3, #4633).
 *
 * Two servers can both expose "10 tools" yet differ wildly in how hard they are to call. This module
 * is the *pure*, React-free layer that turns the per-tool `tool_complexity` list the 14.1 surface
 * metrics already carry (parameter count, required vs optional split, max nesting depth, `enum` /
 * `oneOf` usage, `output_schema` presence) into the view models the 15.3 schema-shape cards render:
 *
 * - a deterministic composite {@link mcpToolComplexityScore complexity score} and its coarse
 *   {@link mcpComplexityTierOf tier}, so tools can be ranked "most / least complex";
 * - the required-vs-optional split as a mini-bar geometry;
 * - {@link mcpSortToolViews sort} and {@link mcpFilterToolViews filter} projections (both total and
 *   stable) for the sortable card view;
 * - a {@link mcpComplexityHistogram histogram} of the tool distribution across complexity tiers.
 *
 * Keeping this free of React/JSX lets it be unit-tested directly and keeps the panel component free
 * of scoring/sorting/binning branches. Colors/spacing never appear here — a tier carries a *tone
 * token* (a {@link ChartSeriesTone}) the consumer maps to classes, never a hex/Tailwind literal.
 */

import type { ChartSeriesTone } from '@/app/components/ui/mcp/charts';
import type { McpToolComplexity } from './mcpInsightUi';

// --- Complexity scoring ----------------------------------------------------------------------

/**
 * Weights the composite complexity score assigns to each schema signal. Chosen so the score reads
 * as "how much a caller must reason about to invoke this tool correctly":
 *
 * - every top-level parameter is one unit of surface;
 * - each level of *nesting* past a flat object multiplies the reading cost, so it is weighted more
 *   heavily than a single parameter;
 * - a `oneOf` (polymorphic argument) forces the caller to pick a branch — the costliest single
 *   signal; an `enum` merely constrains one field, so it is the cheapest.
 *
 * `output_schema` presence is deliberately *not* scored: declaring an output schema makes a tool
 * easier to consume, not harder, so it is surfaced as a badge, never as complexity.
 */
export const COMPLEXITY_WEIGHTS = {
  perProperty: 1,
  perNestingLevel: 2,
  oneOf: 3,
  enum: 1,
} as const;

/**
 * A deterministic, non-negative composite complexity score for one tool's input schema.
 *
 * `score = property_count·1 + max_nesting_depth·2 + (oneOf ? 3 : 0) + (enum ? 1 : 0)`.
 *
 * A tool with no parameters scores `0`. The score is monotonic in every input (more params, deeper
 * nesting, or an added combinator never lowers it), so ranking by it is stable and explainable. All
 * inputs are read through `Math.max(0, …)` so a malformed negative count can never produce a
 * negative score.
 */
export function mcpToolComplexityScore(metrics: McpToolComplexity): number {
  const properties = Math.max(0, metrics.property_count);
  const depth = Math.max(0, metrics.max_nesting_depth);
  return (
    properties * COMPLEXITY_WEIGHTS.perProperty +
    depth * COMPLEXITY_WEIGHTS.perNestingLevel +
    (metrics.uses_one_of ? COMPLEXITY_WEIGHTS.oneOf : 0) +
    (metrics.uses_enum ? COMPLEXITY_WEIGHTS.enum : 0)
  );
}

// --- Complexity tiers ------------------------------------------------------------------------

/** The five complexity tiers a tool (and the distribution histogram) is bucketed into, low→high. */
export type McpComplexityTierKey = 'none' | 'low' | 'moderate' | 'high' | 'very-high';

/** A complexity tier: its key, human label, inclusive score range, and categorical tone token. */
export interface McpComplexityTier {
  key: McpComplexityTierKey;
  label: string;
  /** Inclusive lower score bound. */
  min: number;
  /** Inclusive upper score bound (`Infinity` for the open-ended top tier). */
  max: number;
  /** Categorical tone token the consumer maps to chart/badge classes (never a color literal here). */
  tone: ChartSeriesTone;
}

/**
 * The complexity tiers in ascending order. Thresholds are fixed (not data-relative) so the same tool
 * always lands in the same tier regardless of the surface it is viewed alongside — a server's "High"
 * tool reads the same as another's. `none` is reserved for zero-parameter tools (score `0`); the
 * remaining bands widen as they climb, matching how quickly reading cost grows with nesting/combinators.
 */
export const COMPLEXITY_TIERS: readonly McpComplexityTier[] = [
  { key: 'none', label: 'None', min: 0, max: 0, tone: 'neutral' },
  { key: 'low', label: 'Low', min: 1, max: 4, tone: 'emerald' },
  { key: 'moderate', label: 'Moderate', min: 5, max: 9, tone: 'blue' },
  { key: 'high', label: 'High', min: 10, max: 17, tone: 'amber' },
  { key: 'very-high', label: 'Very high', min: 18, max: Infinity, tone: 'red' },
];

/**
 * Resolve a complexity `score` to its {@link McpComplexityTier}. Totals gracefully: a negative or
 * non-finite score clamps into the lowest (`none`) tier and any score above the top threshold lands
 * in `very-high`, so every input maps to exactly one tier.
 */
export function mcpComplexityTierOf(score: number): McpComplexityTier {
  const s = Number.isFinite(score) ? Math.max(0, score) : 0;
  for (const tier of COMPLEXITY_TIERS) {
    if (s >= tier.min && s <= tier.max) return tier;
  }
  // Unreachable for finite inputs (the top tier is open-ended), but keep the function total.
  return COMPLEXITY_TIERS[COMPLEXITY_TIERS.length - 1];
}

// --- Per-tool view model ---------------------------------------------------------------------

/** The fallback label for a tool whose server omitted its programmatic name. */
export const UNNAMED_TOOL_LABEL = '(unnamed tool)';

/** A presentation-ready complexity profile for one tool card. */
export interface McpToolComplexityView {
  /** The tool's programmatic name (may be empty when the server omitted it). */
  name: string;
  /** The name to show — {@link UNNAMED_TOOL_LABEL} when the tool is unnamed. */
  displayName: string;
  /** The tool's original ordinal in the surface, used as the final stable sort tie-break. */
  index: number;
  /** The raw per-tool metrics this view is derived from. */
  metrics: McpToolComplexity;
  /** The composite {@link mcpToolComplexityScore complexity score}. */
  score: number;
  /** The {@link McpComplexityTier} the score falls in. */
  tier: McpComplexityTier;
  /** Required top-level parameter count (clamped ≥ 0). */
  requiredCount: number;
  /** Optional top-level parameter count (clamped ≥ 0). */
  optionalCount: number;
  /** Required share of parameters as a 0-100 percentage (`0` when the tool has no parameters). */
  requiredPct: number;
  /** Optional share of parameters as a 0-100 percentage (`0` when the tool has no parameters). */
  optionalPct: number;
}

/** Build the {@link McpToolComplexityView} for one tool at ordinal `index`. */
function toolViewFrom(metrics: McpToolComplexity, index: number): McpToolComplexityView {
  const score = mcpToolComplexityScore(metrics);
  const propertyCount = Math.max(0, metrics.property_count);
  // Clamp required into `[0, propertyCount]` so the mini bar can never overflow or go negative even
  // if a malformed payload reports more required params than it declares properties.
  const requiredCount = Math.min(propertyCount, Math.max(0, metrics.required_count));
  const optionalCount = propertyCount - requiredCount;
  const requiredPct = propertyCount > 0 ? (requiredCount / propertyCount) * 100 : 0;
  const name = typeof metrics.name === 'string' ? metrics.name : '';
  return {
    name,
    displayName: name.trim().length > 0 ? name : UNNAMED_TOOL_LABEL,
    index,
    metrics,
    score,
    tier: mcpComplexityTierOf(score),
    requiredCount,
    optionalCount,
    requiredPct,
    optionalPct: propertyCount > 0 ? 100 - requiredPct : 0,
  };
}

/** Build the per-tool complexity views for a surface's `tool_complexity` list, in surface order. */
export function mcpToolComplexityViews(
  tools: readonly McpToolComplexity[],
): McpToolComplexityView[] {
  return tools.map((tool, index) => toolViewFrom(tool, index));
}

// --- Sorting ---------------------------------------------------------------------------------

/** The tool-card sort orders the panel offers. */
export type McpToolSortKey =
  | 'complexity-desc'
  | 'complexity-asc'
  | 'name-asc'
  | 'params-desc'
  | 'depth-desc';

/** One sort option: its stable key and the label shown in the selector. */
export interface McpToolSortOption {
  key: McpToolSortKey;
  label: string;
}

/** The sort options in menu order; `complexity-desc` ("Most complex first") is the default. */
export const TOOL_SORT_OPTIONS: readonly McpToolSortOption[] = [
  { key: 'complexity-desc', label: 'Most complex first' },
  { key: 'complexity-asc', label: 'Least complex first' },
  { key: 'name-asc', label: 'Name (A–Z)' },
  { key: 'params-desc', label: 'Most parameters' },
  { key: 'depth-desc', label: 'Deepest nesting' },
];

/** The default sort applied before the user picks one. */
export const DEFAULT_TOOL_SORT: McpToolSortKey = 'complexity-desc';

/** Case-insensitive name compare with the empty/unnamed name always sorting last within a name sort. */
function compareByName(a: McpToolComplexityView, b: McpToolComplexityView): number {
  return a.displayName.localeCompare(b.displayName, undefined, { sensitivity: 'base' });
}

/**
 * Return a new array of `views` ordered by `sort`. The sort is *stable* and *total*: every comparator
 * falls back to case-insensitive name, then original surface order (`index`), so equal-scoring tools
 * keep a deterministic order and an unknown `sort` degrades to the default. The input is never mutated.
 */
export function mcpSortToolViews(
  views: readonly McpToolComplexityView[],
  sort: McpToolSortKey = DEFAULT_TOOL_SORT,
): McpToolComplexityView[] {
  const byIndex = (a: McpToolComplexityView, b: McpToolComplexityView) => a.index - b.index;
  const withTieBreak =
    (primary: (a: McpToolComplexityView, b: McpToolComplexityView) => number) =>
    (a: McpToolComplexityView, b: McpToolComplexityView) =>
      primary(a, b) || compareByName(a, b) || byIndex(a, b);

  let comparator: (a: McpToolComplexityView, b: McpToolComplexityView) => number;
  switch (sort) {
    case 'complexity-asc':
      comparator = withTieBreak((a, b) => a.score - b.score);
      break;
    case 'name-asc':
      comparator = withTieBreak(compareByName);
      break;
    case 'params-desc':
      comparator = withTieBreak((a, b) => b.metrics.property_count - a.metrics.property_count);
      break;
    case 'depth-desc':
      comparator = withTieBreak((a, b) => b.metrics.max_nesting_depth - a.metrics.max_nesting_depth);
      break;
    case 'complexity-desc':
    default:
      comparator = withTieBreak((a, b) => b.score - a.score);
      break;
  }
  return [...views].sort(comparator);
}

// --- Filtering -------------------------------------------------------------------------------

/** The tool-card filters the panel offers. */
export type McpToolFilterKey =
  | 'all'
  | 'with-params'
  | 'no-params'
  | 'nested'
  | 'enum'
  | 'one-of'
  | 'output-schema'
  | 'no-output-schema';

/** One filter option: its stable key, the label shown in the selector, and its predicate. */
export interface McpToolFilterOption {
  key: McpToolFilterKey;
  label: string;
  /** True when a tool passes this filter. */
  predicate: (view: McpToolComplexityView) => boolean;
}

/** The filter options in menu order; `all` is the default (no filtering). */
export const TOOL_FILTER_OPTIONS: readonly McpToolFilterOption[] = [
  { key: 'all', label: 'All tools', predicate: () => true },
  { key: 'with-params', label: 'Has parameters', predicate: (v) => v.metrics.property_count > 0 },
  { key: 'no-params', label: 'No parameters', predicate: (v) => v.metrics.property_count === 0 },
  { key: 'nested', label: 'Nested schema', predicate: (v) => v.metrics.max_nesting_depth > 1 },
  { key: 'enum', label: 'Uses enum', predicate: (v) => v.metrics.uses_enum },
  { key: 'one-of', label: 'Uses oneOf', predicate: (v) => v.metrics.uses_one_of },
  { key: 'output-schema', label: 'Has output schema', predicate: (v) => v.metrics.has_output_schema },
  {
    key: 'no-output-schema',
    label: 'Missing output schema',
    predicate: (v) => !v.metrics.has_output_schema,
  },
];

/** The default filter applied before the user picks one. */
export const DEFAULT_TOOL_FILTER: McpToolFilterKey = 'all';

/**
 * Return the subset of `views` passing filter `filter`. Total: an unknown key degrades to `all` (no
 * filtering). Order is preserved; the input is never mutated. Combine with {@link mcpSortToolViews}
 * (filter, then sort) to drive the card view.
 */
export function mcpFilterToolViews(
  views: readonly McpToolComplexityView[],
  filter: McpToolFilterKey = DEFAULT_TOOL_FILTER,
): McpToolComplexityView[] {
  const option = TOOL_FILTER_OPTIONS.find((o) => o.key === filter);
  if (!option || option.key === 'all') return [...views];
  return views.filter(option.predicate);
}

// --- Distribution histogram ------------------------------------------------------------------

/** One histogram bar: a complexity tier and how many of the surface's tools fall in it. */
export interface McpComplexityHistogramBin {
  key: McpComplexityTierKey;
  label: string;
  count: number;
  tone: ChartSeriesTone;
}

/**
 * Bin `views` into one bar per {@link COMPLEXITY_TIERS complexity tier}, in ascending tier order.
 * Every tier is always present (a zero-count bar renders as an empty column), so the histogram's
 * shape is stable across surfaces and reads as a true distribution rather than a sparse list.
 */
export function mcpComplexityHistogram(
  views: readonly McpToolComplexityView[],
): McpComplexityHistogramBin[] {
  const counts = new Map<McpComplexityTierKey, number>(
    COMPLEXITY_TIERS.map((tier) => [tier.key, 0]),
  );
  for (const view of views) {
    counts.set(view.tier.key, (counts.get(view.tier.key) ?? 0) + 1);
  }
  return COMPLEXITY_TIERS.map((tier) => ({
    key: tier.key,
    label: tier.label,
    count: counts.get(tier.key) ?? 0,
    tone: tier.tone,
  }));
}
