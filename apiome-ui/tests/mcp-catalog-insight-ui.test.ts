/**
 * Unit tests for the pure catalog-analytics client helpers (V2-MCP-32.1 / MCAT-18.1).
 *
 * Exercises `mcpCatalogInsightUi` in isolation (no React): the defensive parser (scalar tallies,
 * type counts, the grade map → sorted buckets, the composition breakdowns, and the malformed/empty
 * paths), and the presentation projections (empty detection, percentages, grade tones, donut/bar
 * projections).
 */
import {
  mcpCatalogBars,
  mcpCatalogDonutSegments,
  mcpCatalogGradeTone,
  mcpCatalogInsightFromPayload,
  mcpCatalogIsEmpty,
  mcpCatalogPercent,
} from '../src/app/components/ade/dashboard/mcp/mcpCatalogInsightUi';

function populatedPayload(extra: Record<string, unknown> = {}) {
  return {
    success: true,
    endpoint_count: 12,
    published_count: 7,
    public_count: 5,
    private_count: 7,
    discovered_count: 10,
    scored_count: 9,
    average_score: 78.4,
    type_counts: { tools: 84, resources: 22, resource_templates: 5, prompts: 8, total: 119 },
    grade_distribution: { B: 4, A: 3, D: 1, C: 1 },
    category_distribution: [
      { label: 'search', count: 4 },
      { label: 'Uncategorized', count: 2 },
    ],
    transport_distribution: [{ label: 'streamable_http', count: 8 }],
    protocol_version_distribution: [{ label: '2025-06-18', count: 6 }],
    tool_count_distribution: [
      { label: '0', count: 2 },
      { label: '1–5', count: 4 },
    ],
    discovery_health: [{ label: 'ok', count: 9 }],
    change_leaders: [{ endpoint_id: 'ep-1', name: 'Acme Search', change_count: 23 }],
    top_capabilities: [{ item_type: 'tool', item_name: 'search', endpoint_count: 6 }],
    ...extra,
  };
}

describe('mcpCatalogInsightFromPayload', () => {
  it('parses the full payload into the typed model', () => {
    const insight = mcpCatalogInsightFromPayload(populatedPayload())!;
    expect(insight).not.toBeNull();
    expect(insight.endpointCount).toBe(12);
    expect(insight.discoveredCount).toBe(10);
    expect(insight.averageScore).toBeCloseTo(78.4);
    expect(insight.typeCounts).toEqual({
      tools: 84,
      resources: 22,
      resourceTemplates: 5,
      prompts: 8,
      total: 119,
    });
    expect(insight.categoryDistribution).toEqual([
      { label: 'search', count: 4 },
      { label: 'Uncategorized', count: 2 },
    ]);
    expect(insight.changeLeaders[0]).toEqual({
      endpointId: 'ep-1',
      name: 'Acme Search',
      changeCount: 23,
    });
    expect(insight.topCapabilities[0]).toEqual({
      itemType: 'tool',
      itemName: 'search',
      endpointCount: 6,
    });
  });

  it('sorts the grade distribution ascending by grade', () => {
    const insight = mcpCatalogInsightFromPayload(populatedPayload())!;
    expect(insight.gradeDistribution).toEqual([
      { label: 'A', count: 3 },
      { label: 'B', count: 4 },
      { label: 'C', count: 1 },
      { label: 'D', count: 1 },
    ]);
  });

  it('parses an empty catalog into all-empty breakdowns with a null average', () => {
    const insight = mcpCatalogInsightFromPayload({
      success: true,
      endpoint_count: 0,
      published_count: 0,
      public_count: 0,
      private_count: 0,
      discovered_count: 0,
      scored_count: 0,
      average_score: null,
      type_counts: { tools: 0, resources: 0, resource_templates: 0, prompts: 0, total: 0 },
      grade_distribution: {},
    })!;
    expect(insight.endpointCount).toBe(0);
    expect(insight.averageScore).toBeNull();
    expect(insight.gradeDistribution).toEqual([]);
    expect(insight.categoryDistribution).toEqual([]);
    expect(insight.changeLeaders).toEqual([]);
    expect(insight.topCapabilities).toEqual([]);
    expect(mcpCatalogIsEmpty(insight)).toBe(true);
  });

  it('drops malformed breakdown/leader/capability entries defensively', () => {
    const insight = mcpCatalogInsightFromPayload(
      populatedPayload({
        category_distribution: [{ label: 'ok', count: 3 }, { count: 9 }, { label: '', count: 1 }],
        change_leaders: [{ name: 'no id', change_count: 4 }, { endpoint_id: 'e', name: 'kept', change_count: 1 }],
        top_capabilities: [{ item_type: 'tool', endpoint_count: 2 }, { item_name: 'kept', endpoint_count: 1 }],
      }),
    )!;
    expect(insight.categoryDistribution).toEqual([{ label: 'ok', count: 3 }]);
    expect(insight.changeLeaders).toEqual([{ endpointId: 'e', name: 'kept', changeCount: 1 }]);
    expect(insight.topCapabilities).toEqual([{ itemType: '', itemName: 'kept', endpointCount: 1 }]);
  });

  it('falls back to the endpoint id when a change leader has no name', () => {
    const insight = mcpCatalogInsightFromPayload(
      populatedPayload({ change_leaders: [{ endpoint_id: 'ep-x', change_count: 2 }] }),
    )!;
    expect(insight.changeLeaders[0]).toEqual({ endpointId: 'ep-x', name: 'ep-x', changeCount: 2 });
  });

  it('returns null for a malformed or error-envelope payload', () => {
    expect(mcpCatalogInsightFromPayload(null)).toBeNull();
    expect(mcpCatalogInsightFromPayload('nope')).toBeNull();
    expect(mcpCatalogInsightFromPayload({ success: false, error: 'boom' })).toBeNull();
  });
});

describe('presentation helpers', () => {
  it('computes whole-number percentages and never divides by zero', () => {
    expect(mcpCatalogPercent(3, 12)).toBe(25);
    expect(mcpCatalogPercent(1, 3)).toBe(33);
    expect(mcpCatalogPercent(5, 0)).toBe(0);
  });

  it('tones grades A/B green, C amber, and D-and-below red', () => {
    expect(mcpCatalogGradeTone('A')).toBe('emerald');
    expect(mcpCatalogGradeTone('b')).toBe('emerald');
    expect(mcpCatalogGradeTone('C')).toBe('amber');
    expect(mcpCatalogGradeTone('D')).toBe('red');
    expect(mcpCatalogGradeTone('F')).toBe('red');
  });

  it('projects buckets onto donut segments with stable categorical tones', () => {
    const segments = mcpCatalogDonutSegments([
      { label: 'a', count: 3 },
      { label: 'b', count: 1 },
    ]);
    expect(segments.map((s) => s.label)).toEqual(['a', 'b']);
    expect(segments.map((s) => s.value)).toEqual([3, 1]);
    // distinct, resolved tones (the exact palette order lives in chartTokens).
    expect(new Set(segments.map((s) => s.tone)).size).toBe(2);
  });

  it('honors a per-bucket tone override for the grade donut', () => {
    const segments = mcpCatalogDonutSegments(
      [{ label: 'A', count: 3 }, { label: 'D', count: 1 }],
      (bucket) => mcpCatalogGradeTone(bucket.label),
    );
    expect(segments.map((s) => s.tone)).toEqual(['emerald', 'red']);
  });

  it('projects buckets onto uniformly-toned bar data', () => {
    const bars = mcpCatalogBars([{ label: '0', count: 2 }], 'indigo');
    expect(bars).toEqual([{ label: '0', value: 2, tone: 'indigo' }]);
  });
});
