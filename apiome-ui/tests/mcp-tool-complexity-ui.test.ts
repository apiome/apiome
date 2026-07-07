/**
 * Unit tests for the MCP tool schema-shape & complexity presentation helpers (V2-MCP-29.3 /
 * MCAT-15.3, #4633).
 *
 * Exercises the pure layer over the 14.1 `tool_complexity` metrics: the composite complexity score
 * and its weighting, tier bucketing (including the zero-param and huge-schema edges), the per-tool
 * view models (required/optional split, unnamed fallback, clamping), the stable sort orders, the
 * filter predicates, and the tier-distribution histogram.
 */

import type { McpToolComplexity } from '../src/app/components/ade/dashboard/mcp/mcpInsightUi';
import {
  COMPLEXITY_TIERS,
  COMPLEXITY_WEIGHTS,
  DEFAULT_TOOL_FILTER,
  DEFAULT_TOOL_SORT,
  TOOL_FILTER_OPTIONS,
  TOOL_SORT_OPTIONS,
  UNNAMED_TOOL_LABEL,
  mcpComplexityHistogram,
  mcpComplexityTierOf,
  mcpFilterToolViews,
  mcpSortToolViews,
  mcpToolComplexityScore,
  mcpToolComplexityViews,
} from '../src/app/components/ade/dashboard/mcp/mcpToolComplexityUi';

/** A fully-specified tool-complexity metric with sane defaults, overridable per test. */
function tool(overrides: Partial<McpToolComplexity> = {}): McpToolComplexity {
  return {
    name: 'do_thing',
    property_count: 0,
    required_count: 0,
    optional_count: 0,
    documented_property_count: 0,
    max_nesting_depth: 0,
    uses_enum: false,
    uses_one_of: false,
    has_output_schema: false,
    ...overrides,
  };
}

describe('mcpToolComplexityScore', () => {
  it('scores a no-parameter tool as 0', () => {
    expect(mcpToolComplexityScore(tool())).toBe(0);
  });

  it('sums the weighted signals (params + nesting·2 + oneOf·3 + enum·1)', () => {
    const score = mcpToolComplexityScore(
      tool({ property_count: 4, max_nesting_depth: 3, uses_one_of: true, uses_enum: true }),
    );
    // 4·1 + 3·2 + 3 + 1 = 14
    expect(score).toBe(
      4 * COMPLEXITY_WEIGHTS.perProperty +
        3 * COMPLEXITY_WEIGHTS.perNestingLevel +
        COMPLEXITY_WEIGHTS.oneOf +
        COMPLEXITY_WEIGHTS.enum,
    );
    expect(score).toBe(14);
  });

  it('is monotonic — adding any signal never lowers the score', () => {
    const base = mcpToolComplexityScore(tool({ property_count: 2 }));
    expect(mcpToolComplexityScore(tool({ property_count: 2, uses_enum: true }))).toBeGreaterThan(base);
    expect(mcpToolComplexityScore(tool({ property_count: 3 }))).toBeGreaterThan(base);
    expect(
      mcpToolComplexityScore(tool({ property_count: 2, max_nesting_depth: 1 })),
    ).toBeGreaterThan(base);
  });

  it('never returns a negative score for malformed negative counts', () => {
    expect(mcpToolComplexityScore(tool({ property_count: -5, max_nesting_depth: -3 }))).toBe(0);
  });
});

describe('mcpComplexityTierOf', () => {
  it('maps score 0 to the "none" tier', () => {
    expect(mcpComplexityTierOf(0).key).toBe('none');
  });

  it('maps mid-range scores to the expected tiers', () => {
    expect(mcpComplexityTierOf(1).key).toBe('low');
    expect(mcpComplexityTierOf(4).key).toBe('low');
    expect(mcpComplexityTierOf(5).key).toBe('moderate');
    expect(mcpComplexityTierOf(9).key).toBe('moderate');
    expect(mcpComplexityTierOf(10).key).toBe('high');
    expect(mcpComplexityTierOf(17).key).toBe('high');
    expect(mcpComplexityTierOf(18).key).toBe('very-high');
  });

  it('lands a huge schema in the open-ended top tier', () => {
    expect(mcpComplexityTierOf(9999).key).toBe('very-high');
  });

  it('clamps a negative / non-finite score into the lowest tier', () => {
    expect(mcpComplexityTierOf(-10).key).toBe('none');
    expect(mcpComplexityTierOf(Number.NaN).key).toBe('none');
  });

  it('has contiguous, non-overlapping tier bands starting at 0', () => {
    expect(COMPLEXITY_TIERS[0].min).toBe(0);
    for (let i = 1; i < COMPLEXITY_TIERS.length; i += 1) {
      expect(COMPLEXITY_TIERS[i].min).toBe(COMPLEXITY_TIERS[i - 1].max + 1);
    }
    expect(COMPLEXITY_TIERS[COMPLEXITY_TIERS.length - 1].max).toBe(Infinity);
  });
});

describe('mcpToolComplexityViews', () => {
  it('derives the required/optional split and percentages', () => {
    const [view] = mcpToolComplexityViews([
      tool({ property_count: 4, required_count: 1 }),
    ]);
    expect(view.requiredCount).toBe(1);
    expect(view.optionalCount).toBe(3);
    expect(view.requiredPct).toBe(25);
    expect(view.optionalPct).toBe(75);
  });

  it('renders a no-parameter tool with an empty split (no divide-by-zero)', () => {
    const [view] = mcpToolComplexityViews([tool({ property_count: 0 })]);
    expect(view.requiredCount).toBe(0);
    expect(view.optionalCount).toBe(0);
    expect(view.requiredPct).toBe(0);
    expect(view.optionalPct).toBe(0);
    expect(view.tier.key).toBe('none');
  });

  it('clamps a required count that exceeds the property count', () => {
    const [view] = mcpToolComplexityViews([tool({ property_count: 2, required_count: 9 })]);
    expect(view.requiredCount).toBe(2);
    expect(view.optionalCount).toBe(0);
    expect(view.requiredPct).toBe(100);
  });

  it('falls back to a placeholder label for an unnamed tool but keeps the raw name empty', () => {
    const [view] = mcpToolComplexityViews([tool({ name: '   ' })]);
    expect(view.displayName).toBe(UNNAMED_TOOL_LABEL);
    expect(view.name).toBe('   ');
  });

  it('preserves the surface ordinal as the view index', () => {
    const views = mcpToolComplexityViews([tool({ name: 'a' }), tool({ name: 'b' })]);
    expect(views.map((v) => v.index)).toEqual([0, 1]);
  });
});

describe('mcpSortToolViews', () => {
  const views = mcpToolComplexityViews([
    tool({ name: 'flat', property_count: 2 }), // score 2
    tool({ name: 'deep', property_count: 1, max_nesting_depth: 4 }), // score 9
    tool({ name: 'none' }), // score 0
    tool({ name: 'wide', property_count: 6 }), // score 6
  ]);

  it('defaults to most-complex-first and does not mutate its input', () => {
    const before = views.map((v) => v.name);
    const sorted = mcpSortToolViews(views);
    expect(sorted.map((v) => v.name)).toEqual(['deep', 'wide', 'flat', 'none']);
    expect(views.map((v) => v.name)).toEqual(before);
    expect(DEFAULT_TOOL_SORT).toBe('complexity-desc');
  });

  it('sorts least-complex first', () => {
    expect(mcpSortToolViews(views, 'complexity-asc').map((v) => v.name)).toEqual([
      'none',
      'flat',
      'wide',
      'deep',
    ]);
  });

  it('sorts by name A–Z', () => {
    expect(mcpSortToolViews(views, 'name-asc').map((v) => v.name)).toEqual([
      'deep',
      'flat',
      'none',
      'wide',
    ]);
  });

  it('sorts by most parameters then deepest nesting', () => {
    expect(mcpSortToolViews(views, 'params-desc')[0].name).toBe('wide');
    expect(mcpSortToolViews(views, 'depth-desc')[0].name).toBe('deep');
  });

  it('breaks ties stably by name then original order', () => {
    const tied = mcpToolComplexityViews([
      tool({ name: 'zebra', property_count: 3 }),
      tool({ name: 'alpha', property_count: 3 }),
      tool({ name: 'alpha', property_count: 3 }),
    ]);
    const sorted = mcpSortToolViews(tied, 'complexity-desc');
    // Equal score → name asc (alpha before zebra); equal name → original index (0 before 1).
    expect(sorted.map((v) => v.index)).toEqual([1, 2, 0]);
  });

  it('degrades an unknown sort key to the default order', () => {
    const sorted = mcpSortToolViews(views, 'bogus' as never);
    expect(sorted.map((v) => v.name)).toEqual(['deep', 'wide', 'flat', 'none']);
  });
});

describe('mcpFilterToolViews', () => {
  const views = mcpToolComplexityViews([
    tool({ name: 'none' }),
    tool({ name: 'params', property_count: 3 }),
    tool({ name: 'nested', property_count: 1, max_nesting_depth: 3 }),
    tool({ name: 'enum', property_count: 1, uses_enum: true }),
    tool({ name: 'oneof', property_count: 1, uses_one_of: true }),
    tool({ name: 'output', property_count: 1, has_output_schema: true }),
  ]);

  const names = (filter: Parameters<typeof mcpFilterToolViews>[1]) =>
    mcpFilterToolViews(views, filter).map((v) => v.name);

  it('returns everything for "all" (the default)', () => {
    expect(names('all')).toHaveLength(views.length);
    expect(DEFAULT_TOOL_FILTER).toBe('all');
  });

  it('splits with-params vs no-params', () => {
    expect(names('no-params')).toEqual(['none']);
    expect(names('with-params')).not.toContain('none');
  });

  it('filters by nesting, enum, oneOf, and output-schema presence', () => {
    expect(names('nested')).toEqual(['nested']);
    expect(names('enum')).toEqual(['enum']);
    expect(names('one-of')).toEqual(['oneof']);
    expect(names('output-schema')).toEqual(['output']);
    expect(names('no-output-schema')).not.toContain('output');
  });

  it('degrades an unknown filter key to "all" and never mutates its input', () => {
    const before = views.map((v) => v.name);
    expect(mcpFilterToolViews(views, 'bogus' as never)).toHaveLength(views.length);
    expect(views.map((v) => v.name)).toEqual(before);
  });

  it('exposes every filter/sort option key uniquely', () => {
    const filterKeys = TOOL_FILTER_OPTIONS.map((o) => o.key);
    const sortKeys = TOOL_SORT_OPTIONS.map((o) => o.key);
    expect(new Set(filterKeys).size).toBe(filterKeys.length);
    expect(new Set(sortKeys).size).toBe(sortKeys.length);
  });
});

describe('mcpComplexityHistogram', () => {
  it('always emits one bar per tier in ascending order, even when empty', () => {
    const bins = mcpComplexityHistogram([]);
    expect(bins.map((b) => b.key)).toEqual(['none', 'low', 'moderate', 'high', 'very-high']);
    expect(bins.every((b) => b.count === 0)).toBe(true);
  });

  it('counts tools into their tiers and totals to the tool count', () => {
    const views = mcpToolComplexityViews([
      tool({ name: 'a' }), // none (0)
      tool({ name: 'b', property_count: 2 }), // low (2)
      tool({ name: 'c', property_count: 6 }), // moderate (6)
      tool({ name: 'd', property_count: 10 }), // high (10)
      tool({ name: 'e', property_count: 30 }), // very-high (30)
      tool({ name: 'f', property_count: 3 }), // low (3)
    ]);
    const bins = mcpComplexityHistogram(views);
    const byKey = Object.fromEntries(bins.map((b) => [b.key, b.count]));
    expect(byKey).toEqual({ none: 1, low: 2, moderate: 1, high: 1, 'very-high': 1 });
    expect(bins.reduce((sum, b) => sum + b.count, 0)).toBe(views.length);
  });
});
