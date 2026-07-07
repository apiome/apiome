/**
 * Unit tests for the pure MCP surface-evolution helpers (V2-MCP-30.1 / MCAT-16.1).
 *
 * Exercises the payload parser, the churn-timeline projection the {@link StackedTimeline} renders, and
 * the label/tooltip builders — kept free of React so the counting and column mapping are verified
 * directly. The acceptance criteria checked here: the series parses oldest-first, a zero-churn version
 * still gets a column on the axis, the busiest release is surfaced, and each column maps to the right
 * deep-link `version_id`.
 */
import {
  MCP_CHURN_SERIES,
  mcpChurnColumnLabel,
  mcpChurnTimeline,
  mcpEvolutionPointAxisLabel,
  mcpEvolutionPointDateLabel,
  mcpEvolutionSeriesFromPayload,
  type McpEvolutionPoint,
} from '../src/app/components/ade/dashboard/mcp/mcpEvolutionUi';

/** A wire-shaped evolution point (as apiome-rest's `McpEvolutionPoint` serializes). */
function wirePoint(overrides: Record<string, unknown> = {}) {
  return {
    version_id: 'v-1',
    version_seq: 1,
    version_tag: null,
    discovered_at: '2026-07-01T10:00:00Z',
    is_current: false,
    type_counts: { tools: 2, resources: 1, resource_templates: 0, prompts: 0, total: 3 },
    score: 90,
    grade: 'A',
    change_counts: { added: 3, removed: 0, modified: 0, total: 3 },
    ...overrides,
  };
}

/** A parsed evolution point (post-parser shape). */
function point(overrides: Partial<McpEvolutionPoint> = {}): McpEvolutionPoint {
  return {
    version_id: overrides.version_id ?? 'v-1',
    version_seq: overrides.version_seq ?? 1,
    version_tag: overrides.version_tag ?? null,
    discovered_at: overrides.discovered_at ?? '2026-07-01T10:00:00Z',
    is_current: overrides.is_current ?? false,
    type_counts: overrides.type_counts ?? {
      tools: 2,
      resources: 1,
      resource_templates: 0,
      prompts: 0,
      total: 3,
    },
    score: overrides.score ?? 90,
    grade: overrides.grade ?? 'A',
    change_counts: overrides.change_counts ?? { added: 0, removed: 0, modified: 0, total: 0 },
  };
}

describe('mcpEvolutionSeriesFromPayload', () => {
  it('parses points and re-sorts oldest-first (ascending version_seq)', () => {
    const series = mcpEvolutionSeriesFromPayload({
      success: true,
      endpoint_id: 'ep-1',
      series: [
        wirePoint({ version_id: 'c', version_seq: 3 }),
        wirePoint({ version_id: 'a', version_seq: 1 }),
        wirePoint({ version_id: 'b', version_seq: 2 }),
      ],
    });
    expect(series.map((p) => p.version_seq)).toEqual([1, 2, 3]);
    expect(series.map((p) => p.version_id)).toEqual(['a', 'b', 'c']);
  });

  it('derives type_counts.total and change_counts.total from their parts (ignoring stale totals)', () => {
    const [p] = mcpEvolutionSeriesFromPayload({
      series: [
        wirePoint({
          type_counts: { tools: 4, resources: 2, resource_templates: 1, prompts: 3, total: 999 },
          change_counts: { added: 2, removed: 1, modified: 4, total: 999 },
        }),
      ],
    });
    expect(p.type_counts.total).toBe(10);
    expect(p.change_counts.total).toBe(7);
  });

  it('drops malformed points (no version_id) but keeps the rest', () => {
    const series = mcpEvolutionSeriesFromPayload({
      series: [wirePoint({ version_id: 'a', version_seq: 1 }), { version_seq: 2 }, null],
    });
    expect(series.map((p) => p.version_id)).toEqual(['a']);
  });

  it('returns an empty array for a missing/empty series (never throws)', () => {
    expect(mcpEvolutionSeriesFromPayload({})).toEqual([]);
    expect(mcpEvolutionSeriesFromPayload({ series: [] })).toEqual([]);
    expect(mcpEvolutionSeriesFromPayload(null)).toEqual([]);
    expect(mcpEvolutionSeriesFromPayload({ series: 'nope' })).toEqual([]);
  });

  it('coerces a missing is_current / score / grade defensively', () => {
    const [p] = mcpEvolutionSeriesFromPayload({
      series: [wirePoint({ is_current: undefined, score: null, grade: undefined })],
    });
    expect(p.is_current).toBe(false);
    expect(p.score).toBeNull();
    expect(p.grade).toBeNull();
  });
});

describe('mcpChurnTimeline', () => {
  const series: McpEvolutionPoint[] = [
    point({ version_id: 'a', version_seq: 1, change_counts: { added: 5, removed: 0, modified: 0, total: 5 } }),
    // A quiet release — zero churn.
    point({ version_id: 'b', version_seq: 2, change_counts: { added: 0, removed: 0, modified: 0, total: 0 } }),
    point({
      version_id: 'c',
      version_seq: 3,
      is_current: true,
      change_counts: { added: 2, removed: 3, modified: 4, total: 9 },
    }),
  ];

  it('projects one column per snapshot, oldest→newest, with the three churn bands', () => {
    const t = mcpChurnTimeline(series);
    expect(t.series).toBe(MCP_CHURN_SERIES);
    expect(t.series.map((s) => s.key)).toEqual(['added', 'removed', 'modified']);
    expect(t.periods.map((p) => p.label)).toEqual(['v1', 'v2', 'v3']);
    expect(t.versionIds).toEqual(['a', 'b', 'c']);
  });

  it('keeps a zero-churn version as an (empty) column on the axis', () => {
    const t = mcpChurnTimeline(series);
    // v2 still has a period; all three band values are 0.
    expect(t.periods[1].values).toEqual({ added: 0, removed: 0, modified: 0 });
  });

  it('splits each column into added / removed / modified', () => {
    const t = mcpChurnTimeline(series);
    expect(t.periods[0].values).toEqual({ added: 5, removed: 0, modified: 0 });
    expect(t.periods[2].values).toEqual({ added: 2, removed: 3, modified: 4 });
  });

  it('reports total churn, the current column, and the busiest column', () => {
    const t = mcpChurnTimeline(series);
    expect(t.totalChurn).toBe(14);
    expect(t.currentIndex).toBe(2);
    expect(t.busiestIndex).toBe(2); // v3 has the most churn (9)
  });

  it('reports no busiest column when every snapshot is churn-free', () => {
    const flat = [
      point({ version_id: 'a', version_seq: 1, change_counts: { added: 0, removed: 0, modified: 0, total: 0 } }),
      point({ version_id: 'b', version_seq: 2, change_counts: { added: 0, removed: 0, modified: 0, total: 0 } }),
    ];
    const t = mcpChurnTimeline(flat);
    expect(t.busiestIndex).toBe(-1);
    expect(t.totalChurn).toBe(0);
  });

  it('breaks a busiest-column tie toward the earliest such version', () => {
    const tied = [
      point({ version_id: 'a', version_seq: 1, change_counts: { added: 4, removed: 0, modified: 0, total: 4 } }),
      point({ version_id: 'b', version_seq: 2, change_counts: { added: 4, removed: 0, modified: 0, total: 4 } }),
    ];
    expect(mcpChurnTimeline(tied).busiestIndex).toBe(0);
  });

  it('handles an empty series without throwing', () => {
    const t = mcpChurnTimeline([]);
    expect(t.periods).toEqual([]);
    expect(t.versionIds).toEqual([]);
    expect(t.currentIndex).toBe(-1);
    expect(t.busiestIndex).toBe(-1);
    expect(t.totalChurn).toBe(0);
  });
});

describe('label helpers', () => {
  it('labels a column by its version sequence', () => {
    expect(mcpEvolutionPointAxisLabel(point({ version_seq: 7 }))).toBe('v7');
  });

  it('prefers the version_tag, then a formatted discovered_at, for the date label', () => {
    expect(mcpEvolutionPointDateLabel(point({ version_tag: '2026-07-06' }))).toBe('2026-07-06');
    // With no tag it formats discovered_at (locale-dependent, so just assert it is non-empty and not the tag).
    const label = mcpEvolutionPointDateLabel(point({ version_tag: null, discovered_at: '2026-07-01T10:00:00Z' }));
    expect(label.length).toBeGreaterThan(0);
    // Falls back to the seq label when there is neither tag nor timestamp. (Spread to set an explicit
    // null discovered_at — the `point()` helper's `??` default would otherwise fill it back in.)
    expect(
      mcpEvolutionPointDateLabel({ ...point({ version_seq: 4 }), version_tag: null, discovered_at: null }),
    ).toBe('v4');
  });

  it('builds an accessible column label with the per-direction split and a call to action', () => {
    const label = mcpChurnColumnLabel(
      point({ version_seq: 3, version_tag: '2026-07-06', change_counts: { added: 2, removed: 1, modified: 0, total: 3 } }),
    );
    expect(label).toContain('v3');
    expect(label).toContain('2026-07-06');
    expect(label).toContain('+2 −1 ~0');
    expect(label).toContain('3 changes');
    expect(label).toContain('Click to view the diff');
  });

  it('singularizes a one-change column label', () => {
    const label = mcpChurnColumnLabel(
      point({ change_counts: { added: 1, removed: 0, modified: 0, total: 1 } }),
    );
    expect(label).toContain('(1 change)');
  });
});
