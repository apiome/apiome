/**
 * Unit tests for the MCP "Insight" presentation helpers (V2-MCP-28.4 / MCAT-14.4, #4630).
 *
 * Exercises the pure parsing/projection layer the Insight tab relies on: defensive parsing of the
 * 14.2 `insight/surface` payload (including malformed/partial bodies), the derived per-kind count
 * tiles, and the documentation-coverage meters — especially their clamping and zero-denominator
 * (never-NaN) behavior.
 */

import {
  mcpCoverageStats,
  mcpInsightSurfaceFromPayload,
  mcpTypeCountTiles,
  type McpSurfaceMetrics,
} from '../src/app/components/ade/dashboard/mcp/mcpInsightUi';

const VERSION_ID = '22222222-2222-4222-8222-222222222222';
const ENDPOINT_ID = '11111111-1111-4111-8111-111111111111';

/** A fully-populated insight/surface payload as apiome-rest would return it. */
function surfacePayload(overrides: Record<string, unknown> = {}) {
  return {
    success: true,
    endpoint_id: ENDPOINT_ID,
    version_id: VERSION_ID,
    version_seq: 3,
    version_tag: '2026-07-06',
    is_current: true,
    metrics: {
      type_counts: { tools: 4, resources: 2, resource_templates: 1, prompts: 1, total: 8 },
      tool_complexity: [
        {
          name: 'search',
          property_count: 3,
          required_count: 1,
          optional_count: 2,
          documented_property_count: 3,
          max_nesting_depth: 2,
          uses_enum: true,
          uses_one_of: false,
          has_output_schema: true,
        },
      ],
      output_schema_count: 3,
      annotation_coverage: {
        tool_count: 4,
        annotated_tools: 3,
        read_only_hint: 2,
        destructive_hint: 1,
        idempotent_hint: 1,
        open_world_hint: 0,
      },
      documentation_coverage: {
        item_count: 8,
        described_items: 6,
        titled_items: 4,
        description_pct: 75,
        title_pct: 50,
        tool_param_count: 10,
        documented_tool_params: 7,
        tool_param_description_pct: 70,
      },
      metrics_fingerprint: 'abc123',
    },
    ...overrides,
  };
}

describe('mcpInsightSurfaceFromPayload', () => {
  it('parses a full surface payload into typed metrics', () => {
    const surface = mcpInsightSurfaceFromPayload(surfacePayload());
    expect(surface).not.toBeNull();
    expect(surface!.version_id).toBe(VERSION_ID);
    expect(surface!.version_seq).toBe(3);
    expect(surface!.version_tag).toBe('2026-07-06');
    expect(surface!.is_current).toBe(true);
    expect(surface!.metrics.type_counts.total).toBe(8);
    expect(surface!.metrics.tool_complexity).toHaveLength(1);
    expect(surface!.metrics.tool_complexity[0].name).toBe('search');
    expect(surface!.metrics.output_schema_count).toBe(3);
    expect(surface!.metrics.metrics_fingerprint).toBe('abc123');
  });

  it('returns null when no resolvable version id is present', () => {
    expect(mcpInsightSurfaceFromPayload({})).toBeNull();
    expect(mcpInsightSurfaceFromPayload({ success: false, error: 'boom' })).toBeNull();
    expect(mcpInsightSurfaceFromPayload(null)).toBeNull();
  });

  it('re-derives total from the parts and defaults missing metric blocks to zero', () => {
    const surface = mcpInsightSurfaceFromPayload({
      endpoint_id: ENDPOINT_ID,
      version_id: VERSION_ID,
      version_seq: 1,
      // total intentionally wrong / absent metric sub-blocks
      metrics: { type_counts: { tools: 2, resources: 1, total: 99 } },
    });
    expect(surface).not.toBeNull();
    expect(surface!.metrics.type_counts.total).toBe(3); // 2 + 1 + 0 + 0, not the bogus 99
    expect(surface!.metrics.tool_complexity).toEqual([]);
    expect(surface!.metrics.documentation_coverage.item_count).toBe(0);
    expect(surface!.metrics.metrics_fingerprint).toBeNull();
    expect(surface!.is_current).toBe(false);
  });
});

describe('mcpTypeCountTiles', () => {
  it('projects the four capability kinds in display order', () => {
    const surface = mcpInsightSurfaceFromPayload(surfacePayload())!;
    const tiles = mcpTypeCountTiles(surface.metrics.type_counts);
    expect(tiles.map((t) => t.key)).toEqual([
      'tools',
      'resources',
      'resource_templates',
      'prompts',
    ]);
    expect(tiles.map((t) => t.value)).toEqual([4, 2, 1, 1]);
    // The grand total is a headline, never a tile.
    expect(tiles.some((t) => (t.key as string) === 'total')).toBe(false);
  });
});

describe('mcpCoverageStats', () => {
  it('maps documentation coverage + output-schema adoption to meters', () => {
    const surface = mcpInsightSurfaceFromPayload(surfacePayload())!;
    const stats = mcpCoverageStats(surface.metrics);
    const byKey = Object.fromEntries(stats.map((s) => [s.key, s]));
    expect(byKey.described.pct).toBe(75);
    expect(byKey.described.have).toBe(6);
    expect(byKey.described.of).toBe(8);
    expect(byKey.titled.pct).toBe(50);
    expect(byKey.params.pct).toBe(70);
    // 3 tools declare an output schema out of 4 → 75%.
    expect(byKey['output-schema'].pct).toBe(75);
    expect(byKey['output-schema'].have).toBe(3);
    expect(byKey['output-schema'].of).toBe(4);
  });

  it('clamps out-of-range percentages and never divides by zero', () => {
    const metrics: McpSurfaceMetrics = {
      type_counts: { tools: 0, resources: 0, resource_templates: 0, prompts: 0, total: 0 },
      tool_complexity: [],
      output_schema_count: 0,
      annotation_coverage: {
        tool_count: 0,
        annotated_tools: 0,
        read_only_hint: 0,
        destructive_hint: 0,
        idempotent_hint: 0,
        open_world_hint: 0,
      },
      documentation_coverage: {
        item_count: 0,
        described_items: 0,
        titled_items: 0,
        description_pct: 150, // out of range
        title_pct: -10, // out of range
        tool_param_count: 0,
        documented_tool_params: 0,
        tool_param_description_pct: 0,
      },
      metrics_fingerprint: null,
    };
    const byKey = Object.fromEntries(mcpCoverageStats(metrics).map((s) => [s.key, s]));
    expect(byKey.described.pct).toBe(100); // clamped from 150
    expect(byKey.titled.pct).toBe(0); // clamped from -10
    // Zero tools → 0%, not NaN.
    expect(byKey['output-schema'].pct).toBe(0);
    expect(Number.isNaN(byKey['output-schema'].pct)).toBe(false);
  });
});
