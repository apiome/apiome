/**
 * Unit tests for the MCP lint & score presentation helpers (V2-MCP-24.4 / MCAT-10.4, #3700).
 *
 * Exercises the pure adapter/derive functions the Lint & Score tab and the Overview grade summary
 * rely on: defensive payload parsing (camelCase and snake_case), MUST/SHOULD/advisory tiering and
 * counts, the per-category count bars (ordering, scaling, worst-severity coloring), and the
 * finding-path → capability-item resolution that powers deep-linking.
 */

import {
  MCP_LINT_SEVERITY_TIER,
  mcpCapabilityAnchorId,
  mcpLintCategoryBars,
  mcpLintCategoryLabel,
  mcpLintFindingTarget,
  mcpLintFindingTier,
  mcpLintGroupByTier,
  mcpLintReportFromPayload,
  mcpLintSeverityBarClass,
  mcpLintTierCounts,
  mcpLintTierMeta,
  type McpLintFinding,
} from '../src/app/components/ade/dashboard/mcp/mcpLintUi';

function makeFinding(overrides: Partial<McpLintFinding> = {}): McpLintFinding {
  return {
    id: overrides.id ?? 'mcp-lint-0001',
    path: overrides.path ?? 'tools.search',
    category: overrides.category ?? 'naming',
    rule: overrides.rule ?? 'naming.item-name-missing',
    severity: overrides.severity ?? 'error',
    message: overrides.message ?? 'Something is wrong.',
  };
}

describe('mcpLintReportFromPayload', () => {
  it('parses the REST camelCase aliases into the snake_case report shape', () => {
    const report = mcpLintReportFromPayload({
      success: true,
      endpointId: 'ep-1',
      versionId: 'v-1',
      versionSeq: 5,
      versionTag: '2026-06-27',
      score: 82,
      grade: 'B',
      findings: [{ id: 'f1', path: 'tools.search', category: 'naming', rule: 'r', severity: 'warning', message: 'm' }],
      ruleHits: { r: 1 },
      severityCounts: { error: 0, warning: 1, info: 0 },
      reportFingerprint: 'abc',
      source: 'stored',
      scoredAt: '2026-06-27T00:00:00Z',
    });
    expect(report).not.toBeNull();
    expect(report).toMatchObject({
      endpoint_id: 'ep-1',
      version_id: 'v-1',
      version_seq: 5,
      version_tag: '2026-06-27',
      score: 82,
      grade: 'B',
      rule_hits: { r: 1 },
      severity_counts: { error: 0, warning: 1, info: 0 },
      report_fingerprint: 'abc',
      source: 'stored',
      scored_at: '2026-06-27T00:00:00Z',
    });
    expect(report?.findings).toHaveLength(1);
    expect(report?.findings[0]).toMatchObject({ path: 'tools.search', severity: 'warning' });
  });

  it('also accepts snake_case originals', () => {
    const report = mcpLintReportFromPayload({
      version_id: 'v-9',
      version_seq: 2,
      score: 50,
      grade: 'F',
      rule_hits: { x: 3 },
      severity_counts: { error: 3 },
      report_fingerprint: 'zzz',
    });
    expect(report?.version_id).toBe('v-9');
    expect(report?.version_seq).toBe(2);
    expect(report?.rule_hits).toEqual({ x: 3 });
  });

  it('returns null when no version id is present', () => {
    expect(mcpLintReportFromPayload({ score: 90 })).toBeNull();
    expect(mcpLintReportFromPayload(null)).toBeNull();
  });

  it('falls back to safe defaults for missing fields', () => {
    const report = mcpLintReportFromPayload({ versionId: 'v-1' });
    expect(report).toMatchObject({
      score: 0,
      grade: 'F',
      findings: [],
      rule_hits: {},
      severity_counts: {},
      source: 'computed',
      version_tag: null,
      scored_at: null,
    });
  });

  it('drops non-numeric tally entries defensively', () => {
    const report = mcpLintReportFromPayload({
      versionId: 'v-1',
      ruleHits: { good: 2, bad: 'nope', skip: null },
    });
    expect(report?.rule_hits).toEqual({ good: 2 });
  });
});

describe('requirement tiers', () => {
  it('maps severities to MUST / SHOULD / advisory', () => {
    expect(MCP_LINT_SEVERITY_TIER.error).toBe('must');
    expect(MCP_LINT_SEVERITY_TIER.warning).toBe('should');
    expect(MCP_LINT_SEVERITY_TIER.info).toBe('advisory');
    expect(mcpLintFindingTier(makeFinding({ severity: 'warning' }))).toBe('should');
    expect(mcpLintFindingTier(makeFinding({ severity: 'mystery' }))).toBe('advisory');
  });

  it('exposes display metadata per tier', () => {
    expect(mcpLintTierMeta('must').label).toBe('MUST');
    expect(mcpLintTierMeta('should').label).toBe('SHOULD');
    expect(mcpLintTierMeta('advisory').badgeVariant).toBe('secondary');
  });

  it('counts findings per tier from the findings themselves', () => {
    const counts = mcpLintTierCounts([
      makeFinding({ severity: 'error' }),
      makeFinding({ severity: 'error' }),
      makeFinding({ severity: 'warning' }),
      makeFinding({ severity: 'info' }),
    ]);
    expect(counts).toEqual({ must: 2, should: 1, advisory: 1 });
  });

  it('groups findings into all three tiers in display order', () => {
    const groups = mcpLintGroupByTier([
      makeFinding({ id: 'a', severity: 'info' }),
      makeFinding({ id: 'b', severity: 'error' }),
      makeFinding({ id: 'c', severity: 'warning' }),
    ]);
    expect(groups.map((g) => g.meta.key)).toEqual(['must', 'should', 'advisory']);
    expect(groups[0].findings.map((f) => f.id)).toEqual(['b']);
    expect(groups[1].findings.map((f) => f.id)).toEqual(['c']);
    expect(groups[2].findings.map((f) => f.id)).toEqual(['a']);
  });
});

describe('mcpLintCategoryBars', () => {
  it('counts per category, orders by count then name, and scales to the busiest', () => {
    const bars = mcpLintCategoryBars([
      makeFinding({ category: 'naming', severity: 'warning' }),
      makeFinding({ category: 'naming', severity: 'error' }),
      makeFinding({ category: 'structure', severity: 'info' }),
    ]);
    expect(bars).toHaveLength(2);
    expect(bars[0]).toMatchObject({ category: 'naming', count: 2, percent: 100 });
    expect(bars[1]).toMatchObject({ category: 'structure', count: 1, percent: 50 });
  });

  it('tints a category bar by its worst severity', () => {
    const [bar] = mcpLintCategoryBars([
      makeFinding({ category: 'security', severity: 'info' }),
      makeFinding({ category: 'security', severity: 'error' }),
    ]);
    expect(bar.severity).toBe('error');
    expect(bar.barClass).toBe(mcpLintSeverityBarClass('error'));
  });

  it('returns an empty list for no findings', () => {
    expect(mcpLintCategoryBars([])).toEqual([]);
  });

  it('breaks count ties alphabetically by category', () => {
    const bars = mcpLintCategoryBars([
      makeFinding({ category: 'structure' }),
      makeFinding({ category: 'annotation' }),
    ]);
    expect(bars.map((b) => b.category)).toEqual(['annotation', 'structure']);
  });
});

describe('mcpLintCategoryLabel', () => {
  it('uses known labels and title-cases unknown ids', () => {
    expect(mcpLintCategoryLabel('naming')).toBe('Naming');
    expect(mcpLintCategoryLabel('annotation')).toBe('Annotations');
    expect(mcpLintCategoryLabel('custom-rule_group')).toBe('Custom Rule Group');
    expect(mcpLintCategoryLabel('')).toBe('Other');
  });
});

describe('mcpLintFindingTarget', () => {
  it('resolves a collection path to its capability item_type and name', () => {
    expect(mcpLintFindingTarget('tools.search')).toEqual({ item_type: 'tool', name: 'search' });
    expect(mcpLintFindingTarget('resourceTemplates.file')).toEqual({
      item_type: 'resource_template',
      name: 'file',
    });
  });

  it('keeps dotted item names intact (splits on the first dot only)', () => {
    expect(mcpLintFindingTarget('prompts.a.b.c')).toEqual({ item_type: 'prompt', name: 'a.b.c' });
  });

  it('returns null for surface-level or unrecognized paths', () => {
    expect(mcpLintFindingTarget('surface')).toBeNull();
    expect(mcpLintFindingTarget('widgets.foo')).toBeNull();
    expect(mcpLintFindingTarget('.leadingdot')).toBeNull();
    expect(mcpLintFindingTarget('tools.')).toBeNull();
  });
});

describe('mcpCapabilityAnchorId', () => {
  it('is stable and id-safe across both producers', () => {
    expect(mcpCapabilityAnchorId('tool', 'search')).toBe('mcp-cap-tool-search');
    // A lint finding resolves to the same anchor a capability card renders.
    const target = mcpLintFindingTarget('tools.search')!;
    expect(mcpCapabilityAnchorId(target.item_type, target.name)).toBe('mcp-cap-tool-search');
  });

  it('collapses non-id-safe characters in the name to hyphens', () => {
    expect(mcpCapabilityAnchorId('resource', 'file://path to/x')).toBe('mcp-cap-resource-file-path-to-x');
    expect(mcpCapabilityAnchorId('tool', '')).toBe('mcp-cap-tool-unnamed');
  });
});
