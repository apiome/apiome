/**
 * Unit tests for the side-by-side server comparison pure helpers (V2-MCP-32.2 / MCAT-18.2).
 *
 * Covers the acceptance criteria that live in the pure layer: the comparison aligns metrics
 * column-by-column with a correct `differs` flag; differing protocol versions are handled; and the
 * capability-overlap set (shared vs unique tools) is correct against a fixture. The render concerns
 * are covered in `mcp-server-comparison-panel.test.tsx`.
 */

import type { McpCapabilityItem } from '../src/app/components/ade/dashboard/mcp/mcpBrowseUi';
import { mcpTrustProfileFromPayload } from '../src/app/components/ade/dashboard/mcp/mcpTrustUi';
import { mcpToolReliabilityFromPayload } from '../src/app/components/ade/dashboard/mcp/mcpReliabilityUi';
import {
  mcpCompareSurfaceCounts,
  mcpCompareToolNames,
  mcpToolOverlap,
  mcpCompareProtocolVersions,
  mcpCompareModel,
  type McpCompareServer,
} from '../src/app/components/ade/dashboard/mcp/mcpServerCompareUi';

// --- Fixture builders ------------------------------------------------------------------------

/** Build a capability item with sane defaults; `extra` overrides any field. */
function item(
  item_type: string,
  name: string,
  extra: Partial<McpCapabilityItem> = {},
): McpCapabilityItem {
  return {
    item_type,
    name,
    title: null,
    description: null,
    uri: null,
    uri_template: null,
    input_schema: null,
    output_schema: null,
    annotations: null,
    ordinal: 0,
    ...extra,
  };
}

/** Build a trust profile through the real parser (so the fixture matches production shaping). */
function trust(overall: number, safety: number) {
  return mcpTrustProfileFromPayload({
    version_id: 'v1',
    auth_type: 'bearer',
    profile: {
      axes: [
        { key: 'quality', label: 'Quality', value: overall, available: true, detail: '', methodology: '' },
        { key: 'safety', label: 'Safety', value: safety, available: true, detail: '', methodology: '' },
        { key: 'documentation', label: 'Documentation', value: 70, available: true, detail: '', methodology: '' },
      ],
    },
  });
}

/** Build a reliability roll-up through the real parser. */
function reliability(p95: number, calls: number, errors: number) {
  return mcpToolReliabilityFromPayload({
    tools: {
      tools: [
        {
          tool_name: 'search',
          call_count: calls,
          error_count: errors,
          success_count: calls - errors,
          latency: { count: calls, p50_ms: p95 / 2, p95_ms: p95, p99_ms: p95 },
        },
      ],
      window_days: 7,
    },
  });
}

/** A comparison server with defaults; `extra` overrides. */
function server(extra: Partial<McpCompareServer> = {}): McpCompareServer {
  return {
    endpointId: 'ep',
    endpointName: 'ep',
    displayName: 'Server',
    transport: 'streamable_http',
    category: 'search',
    protocolVersion: '2025-06-18',
    grade: 'B',
    score: 80,
    authType: 'bearer',
    items: [],
    trust: null,
    reliability: null,
    ...extra,
  };
}

// --- Surface counts --------------------------------------------------------------------------

describe('mcpCompareSurfaceCounts', () => {
  it('tallies items per kind and sums the total', () => {
    const counts = mcpCompareSurfaceCounts([
      item('tool', 'a'),
      item('tool', 'b'),
      item('resource', 'r'),
      item('resource_template', 't'),
      item('prompt', 'p'),
      item('mystery', 'x'), // unknown kinds are ignored
    ]);
    expect(counts).toEqual({ tools: 2, resources: 1, resource_templates: 1, prompts: 1, total: 5 });
  });

  it('is all zeroes for an empty surface', () => {
    expect(mcpCompareSurfaceCounts([])).toEqual({
      tools: 0,
      resources: 0,
      resource_templates: 0,
      prompts: 0,
      total: 0,
    });
  });
});

// --- Tool names ------------------------------------------------------------------------------

describe('mcpCompareToolNames', () => {
  it('returns distinct, non-empty tool names sorted, ignoring non-tools', () => {
    const names = mcpCompareToolNames([
      item('tool', 'zeta'),
      item('tool', 'alpha'),
      item('tool', 'alpha'), // duplicate collapses
      item('tool', '  '), // blank dropped
      item('resource', 'not_a_tool'),
    ]);
    expect(names).toEqual(['alpha', 'zeta']);
  });
});

// --- Capability overlap (the fixture acceptance criterion) ------------------------------------

describe('mcpToolOverlap', () => {
  // Three servers with a deliberately-known tool topology:
  //   A: search, fetch, index      B: search, fetch, crawl      C: search, embed
  // → `search` shared by all three; `fetch` shared by A+B; `index`/`crawl`/`embed` each unique.
  const A = server({ endpointId: 'A', displayName: 'Alpha', items: [
    item('tool', 'search'), item('tool', 'fetch'), item('tool', 'index'),
    item('resource', 'doc'), // non-tools never enter the overlap
  ] });
  const B = server({ endpointId: 'B', displayName: 'Bravo', items: [
    item('tool', 'search'), item('tool', 'fetch'), item('tool', 'crawl'),
  ] });
  const C = server({ endpointId: 'C', displayName: 'Charlie', items: [
    item('tool', 'search'), item('tool', 'embed'),
  ] });

  const overlap = mcpToolOverlap([A, B, C]);

  it('counts the distinct tool names across all servers', () => {
    // search, fetch, index, crawl, embed
    expect(overlap.totalDistinct).toBe(5);
  });

  it('marks tools shared by two or more, most-shared first', () => {
    expect(overlap.shared.map((s) => s.name)).toEqual(['search', 'fetch']);
    const search = overlap.shared.find((s) => s.name === 'search')!;
    expect(search.presentIn).toEqual(['A', 'B', 'C']);
    expect(search.presentCount).toBe(3);
    const fetch = overlap.shared.find((s) => s.name === 'fetch')!;
    expect(fetch.presentIn).toEqual(['A', 'B']);
  });

  it('counts tools shared by every server', () => {
    expect(overlap.sharedByAllCount).toBe(1); // only `search`
  });

  it('groups each server’s unique tools in column order', () => {
    expect(overlap.uniqueByServer).toEqual([
      { endpointId: 'A', displayName: 'Alpha', tools: ['index'] },
      { endpointId: 'B', displayName: 'Bravo', tools: ['crawl'] },
      { endpointId: 'C', displayName: 'Charlie', tools: ['embed'] },
    ]);
  });

  it('partitions every distinct tool into exactly shared or unique', () => {
    const sharedNames = overlap.shared.map((s) => s.name);
    const uniqueNames = overlap.uniqueByServer.flatMap((g) => g.tools);
    expect(new Set([...sharedNames, ...uniqueNames]).size).toBe(overlap.totalDistinct);
    // No name appears in both partitions.
    expect(sharedNames.some((n) => uniqueNames.includes(n))).toBe(false);
  });

  it('reduces to a plain intersection for two servers', () => {
    const two = mcpToolOverlap([A, B]);
    // Both `fetch` and `search` are shared by the two servers (count 2), so the tie breaks by name.
    expect(two.shared.map((s) => s.name)).toEqual(['fetch', 'search']);
    expect(two.sharedByAllCount).toBe(2);
    expect(two.uniqueByServer.find((g) => g.endpointId === 'A')!.tools).toEqual(['index']);
    expect(two.uniqueByServer.find((g) => g.endpointId === 'B')!.tools).toEqual(['crawl']);
  });
});

// --- Protocol version cross-check ------------------------------------------------------------

describe('mcpCompareProtocolVersions', () => {
  it('agrees when every server uses the same version', () => {
    const result = mcpCompareProtocolVersions([
      server({ endpointId: 'A', protocolVersion: '2025-06-18' }),
      server({ endpointId: 'B', protocolVersion: '2025-06-18' }),
    ]);
    expect(result.allMatch).toBe(true);
    expect(result.hasUnknown).toBe(false);
    expect(result.distinct).toEqual(['2025-06-18']);
  });

  it('flags a mismatch when versions differ', () => {
    const result = mcpCompareProtocolVersions([
      server({ endpointId: 'A', protocolVersion: '2025-06-18' }),
      server({ endpointId: 'B', protocolVersion: '2025-03-26' }),
    ]);
    expect(result.allMatch).toBe(false);
    expect(result.distinct).toEqual(['2025-03-26', '2025-06-18']);
    expect(result.perServer).toEqual([
      { endpointId: 'A', protocolVersion: '2025-06-18' },
      { endpointId: 'B', protocolVersion: '2025-03-26' },
    ]);
  });

  it('treats an unknown version as compatible but flags it', () => {
    const result = mcpCompareProtocolVersions([
      server({ endpointId: 'A', protocolVersion: '2025-06-18' }),
      server({ endpointId: 'B', protocolVersion: null }),
    ]);
    expect(result.allMatch).toBe(true); // one known version → not a mismatch
    expect(result.hasUnknown).toBe(true);
    expect(result.distinct).toEqual(['2025-06-18']);
  });
});

// --- Full model alignment --------------------------------------------------------------------

describe('mcpCompareModel', () => {
  const A = server({
    endpointId: 'A',
    displayName: 'Alpha',
    grade: 'A',
    score: 92,
    items: [
      item('tool', 'search', { description: 'Search', title: 'Search', annotations: { destructiveHint: true } }),
      item('tool', 'fetch'),
    ],
    trust: trust(90, 80),
    reliability: reliability(400, 100, 2),
  });
  const B = server({
    endpointId: 'B',
    displayName: 'Bravo',
    grade: 'C',
    score: 65,
    protocolVersion: '2025-03-26',
    items: [item('tool', 'search'), item('tool', 'crawl')],
    trust: trust(60, 50),
    reliability: reliability(1200, 50, 10),
  });

  const model = mcpCompareModel([A, B]);

  it('exposes the six aligned sections in order', () => {
    expect(model.sections.map((s) => s.key)).toEqual([
      'surface',
      'quality',
      'safety',
      'coverage',
      'latency',
      'trust',
    ]);
  });

  it('echoes the servers as the column order', () => {
    expect(model.servers.map((s) => s.endpointId)).toEqual(['A', 'B']);
  });

  it('aligns surface counts and flags the total as differing', () => {
    const surface = model.sections.find((s) => s.key === 'surface')!;
    const total = surface.rows.find((r) => r.key === 'total')!;
    expect(total.cells.map((c) => c.value)).toEqual([2, 2]);
    expect(total.differs).toBe(false); // both have two tools
    const tools = surface.rows.find((r) => r.key === 'tools')!;
    expect(tools.cells.map((c) => c.display)).toEqual(['2', '2']);
  });

  it('flags the grade and score rows as differing', () => {
    const quality = model.sections.find((s) => s.key === 'quality')!;
    const grade = quality.rows.find((r) => r.key === 'grade')!;
    expect(grade.cells.map((c) => c.display)).toEqual(['A', 'C']);
    expect(grade.differs).toBe(true);
    const score = quality.rows.find((r) => r.key === 'score')!;
    expect(score.higherIsBetter).toBe(true);
    expect(score.differs).toBe(true);
  });

  it('surfaces the destructive-tool count in the safety section', () => {
    const safety = model.sections.find((s) => s.key === 'safety')!;
    const destructive = safety.rows.find((r) => r.key === 'destructive')!;
    expect(destructive.cells.map((c) => c.value)).toEqual([1, 0]);
    expect(destructive.higherIsBetter).toBe(false);
    expect(destructive.differs).toBe(true);
  });

  it('formats latency cells and marks lower-is-better', () => {
    const latency = model.sections.find((s) => s.key === 'latency')!;
    const p95 = latency.rows.find((r) => r.key === 'p95')!;
    expect(p95.cells.map((c) => c.display)).toEqual(['400 ms', '1.20 s']);
    expect(p95.higherIsBetter).toBe(false);
  });

  it('aligns the overall trust and each trust axis', () => {
    const trustSection = model.sections.find((s) => s.key === 'trust')!;
    const overall = trustSection.rows.find((r) => r.key === 'trust:overall')!;
    expect(overall.cells.map((c) => c.value)).toEqual([A!.trust!.overall, B!.trust!.overall]);
    // One row per axis (quality/safety/documentation), plus the overall row.
    expect(trustSection.rows.map((r) => r.key)).toEqual([
      'trust:overall',
      'trust:quality',
      'trust:safety',
      'trust:documentation',
    ]);
  });

  it('renders a gap for a server missing trust or reliability', () => {
    const withGaps = mcpCompareModel([A, server({ endpointId: 'Z', trust: null, reliability: null })]);
    const trustSection = withGaps.sections.find((s) => s.key === 'trust')!;
    const overall = trustSection.rows.find((r) => r.key === 'trust:overall')!;
    expect(overall.cells[1]).toEqual({ display: '—', value: null });
    const latency = withGaps.sections.find((s) => s.key === 'latency')!;
    expect(latency.rows.find((r) => r.key === 'p95')!.cells[1]).toEqual({ display: '—', value: null });
  });

  it('carries the overlap and protocol cross-check on the model', () => {
    expect(model.overlap.shared.map((s) => s.name)).toEqual(['search']);
    expect(model.protocol.allMatch).toBe(false); // A=2025-06-18, B=2025-03-26
  });
});
