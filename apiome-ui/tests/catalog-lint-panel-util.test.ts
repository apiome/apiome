/**
 * Unit tests for the pure Lint & Score panel helpers (MFI-25.5, #4090).
 *
 * These cover the data-shaping the inline panel depends on: gauge geometry, choosing real category
 * scores over the severity-breakdown fallback, the fallback ordering, MUST/SHOULD mapping, and the
 * category humanizer — all without React or the DOM.
 */

import {
  catalogEntityAnchorId,
  catalogLintFindingTier,
  catalogLintGroupByTier,
  catalogLintProvenance,
  catalogLintTierCounts,
  CATALOG_LINT_TIER_ORDER,
  clampScore,
  deriveCategorySeverityBreakdown,
  gaugeDashOffset,
  humanizeCategory,
  mustLabelForSeverity,
  resolveCatalogFindingEntity,
  resolveCategoryScores,
} from '../src/app/utils/catalog-lint-panel';
import type { VersionLintFinding } from '../src/app/utils/version-lint-report';

function finding(over: Partial<VersionLintFinding>): VersionLintFinding {
  return {
    id: over.id ?? Math.random().toString(36).slice(2),
    path: over.path ?? 'components.schemas.X',
    category: over.category ?? 'documentation',
    rule: over.rule ?? 'documentation.missing',
    severity: over.severity ?? 'warning',
    message: over.message ?? 'msg',
  };
}

describe('clampScore', () => {
  it('rounds and clamps into the 0–100 range', () => {
    expect(clampScore(87.4)).toBe(87);
    expect(clampScore(87.6)).toBe(88);
    expect(clampScore(-5)).toBe(0);
    expect(clampScore(150)).toBe(100);
  });

  it('coerces non-finite input to 0', () => {
    expect(clampScore(Number.NaN)).toBe(0);
    expect(clampScore(Number.POSITIVE_INFINITY)).toBe(0);
  });
});

describe('gaugeDashOffset', () => {
  const C = 100;
  it('leaves the ring empty at 0 and fills it at 100', () => {
    expect(gaugeDashOffset(0, C)).toBe(100);
    expect(gaugeDashOffset(100, C)).toBe(0);
  });
  it('is linear in the score', () => {
    expect(gaugeDashOffset(75, C)).toBeCloseTo(25);
  });
  it('clamps out-of-range scores', () => {
    expect(gaugeDashOffset(200, C)).toBe(0);
    expect(gaugeDashOffset(-10, C)).toBe(100);
  });
});

describe('resolveCategoryScores', () => {
  it('returns null when categories are absent (pre-MFI-25.6)', () => {
    expect(resolveCategoryScores({ categories: null })).toBeNull();
    expect(resolveCategoryScores({ categories: undefined })).toBeNull();
    expect(resolveCategoryScores(null)).toBeNull();
  });

  it('returns null for an empty array (reads as "not provided")', () => {
    expect(resolveCategoryScores({ categories: [] })).toBeNull();
  });

  it('keeps valid entries, clamps scores, and drops malformed ones', () => {
    const result = resolveCategoryScores({
      categories: [
        { name: 'documentation', score: 88.6 },
        { name: 'naming', score: 150 },
        // malformed entries below must be filtered out
        { name: '', score: 50 },
        { name: 'x', score: Number.NaN as unknown as number },
        null as unknown as { name: string; score: number },
      ],
    });
    expect(result).toEqual([
      { name: 'documentation', score: 89 },
      { name: 'naming', score: 100 },
    ]);
  });
});

describe('deriveCategorySeverityBreakdown', () => {
  it('tallies severities per category and totals them', () => {
    const rows = deriveCategorySeverityBreakdown([
      finding({ category: 'documentation', severity: 'warning' }),
      finding({ category: 'documentation', severity: 'info' }),
      finding({ category: 'structure', severity: 'error' }),
    ]);
    const docs = rows.find((r) => r.category === 'documentation');
    expect(docs).toEqual({ category: 'documentation', error: 0, warning: 1, info: 1, total: 2 });
  });

  it('orders categories with the most severe findings first', () => {
    const rows = deriveCategorySeverityBreakdown([
      finding({ category: 'documentation', severity: 'info' }),
      finding({ category: 'documentation', severity: 'info' }),
      finding({ category: 'structure', severity: 'error' }),
    ]);
    // structure (1 error) outranks documentation (2 info) despite fewer findings.
    expect(rows.map((r) => r.category)).toEqual(['structure', 'documentation']);
  });

  it('breaks ties alphabetically and buckets blank categories as "other"', () => {
    const rows = deriveCategorySeverityBreakdown([
      finding({ category: 'naming', severity: 'warning' }),
      finding({ category: 'documentation', severity: 'warning' }),
      finding({ category: '  ', severity: 'warning' }),
    ]);
    expect(rows.map((r) => r.category)).toEqual(['documentation', 'naming', 'other']);
  });

  it('returns [] for no findings', () => {
    expect(deriveCategorySeverityBreakdown([])).toEqual([]);
  });
});

describe('mustLabelForSeverity', () => {
  it('maps error→MUST and everything else→SHOULD', () => {
    expect(mustLabelForSeverity('error')).toBe('MUST');
    expect(mustLabelForSeverity('warning')).toBe('SHOULD');
    expect(mustLabelForSeverity('info')).toBe('SHOULD');
  });
});

describe('humanizeCategory', () => {
  it('sentence-cases and de-slugs the key', () => {
    expect(humanizeCategory('api-design')).toBe('Api design');
    expect(humanizeCategory('documentation')).toBe('Documentation');
    expect(humanizeCategory('best_practices')).toBe('Best practices');
  });
  it('degrades an empty key to "Other"', () => {
    expect(humanizeCategory('   ')).toBe('Other');
  });
});

// --- MFI-28.2: tiers, provenance, and finding → entity deep links -----------------------------

describe('catalogLintFindingTier', () => {
  it('maps severities to requirement tiers (error→must, warning→should, info→advisory)', () => {
    expect(catalogLintFindingTier('error')).toBe('must');
    expect(catalogLintFindingTier('warning')).toBe('should');
    expect(catalogLintFindingTier('info')).toBe('advisory');
  });
  it('defaults unknown severities to advisory', () => {
    expect(catalogLintFindingTier('mystery')).toBe('advisory');
  });
});

describe('catalogLintTierCounts', () => {
  it('tallies findings per tier', () => {
    const counts = catalogLintTierCounts([
      finding({ severity: 'error' }),
      finding({ severity: 'error' }),
      finding({ severity: 'warning' }),
      finding({ severity: 'info' }),
    ]);
    expect(counts).toEqual({ must: 2, should: 1, advisory: 1 });
  });
  it('is all-zero for no findings', () => {
    expect(catalogLintTierCounts([])).toEqual({ must: 0, should: 0, advisory: 0 });
  });
});

describe('catalogLintGroupByTier', () => {
  it('returns every tier in strongest-first order, partitioning findings by severity', () => {
    const err = finding({ id: 'e', severity: 'error' });
    const warn = finding({ id: 'w', severity: 'warning' });
    const groups = catalogLintGroupByTier([warn, err]);
    expect(groups.map((g) => g.meta.key)).toEqual(CATALOG_LINT_TIER_ORDER);
    expect(groups[0].findings).toEqual([err]); // must
    expect(groups[1].findings).toEqual([warn]); // should
    expect(groups[2].findings).toEqual([]); // advisory (empty, still present)
  });
});

describe('catalogLintProvenance', () => {
  it('classifies a never-captured score as computed live', () => {
    const p = catalogLintProvenance({ capturedScore: null, scoreIsStale: false });
    expect(p.source).toBe('computed');
    expect(p.stale).toBe(false);
    expect(p.label).toMatch(/computed/i);
  });
  it('classifies a fresh captured score as stored', () => {
    const p = catalogLintProvenance({ capturedScore: 72, scoreIsStale: false });
    expect(p.source).toBe('stored');
    expect(p.label).toMatch(/stored/i);
  });
  it('classifies a stale captured score as stale', () => {
    const p = catalogLintProvenance({ capturedScore: 40, scoreIsStale: true });
    expect(p.source).toBe('stale');
    expect(p.stale).toBe(true);
  });
});

describe('catalogEntityAnchorId', () => {
  it('builds a stable, id-safe anchor id from an entity name', () => {
    expect(catalogEntityAnchorId('Order')).toBe('catalog-entity-Order');
    expect(catalogEntityAnchorId('Order Line/Item')).toBe('catalog-entity-Order-Line-Item');
  });
  it('degrades a blank name to "unnamed"', () => {
    expect(catalogEntityAnchorId('')).toBe('catalog-entity-unnamed');
  });
});

describe('resolveCatalogFindingEntity', () => {
  const names = new Set(['Order', 'Payment', 'orders']);

  it('matches the deepest path segment that names a known entity', () => {
    expect(resolveCatalogFindingEntity('components.schemas.Order', names)).toBe('Order');
    expect(
      resolveCatalogFindingEntity('components.schemas.Order.properties.total', names),
    ).toBe('Order');
  });
  it('splits on both "." and "/" and is case-sensitive', () => {
    expect(resolveCatalogFindingEntity('paths./orders.get', names)).toBe('orders');
    expect(resolveCatalogFindingEntity('components.schemas.order', names)).toBeNull(); // case differs
  });
  it('returns null when no segment matches or inputs are empty', () => {
    expect(resolveCatalogFindingEntity('info.title', names)).toBeNull();
    expect(resolveCatalogFindingEntity('', names)).toBeNull();
    expect(resolveCatalogFindingEntity('components.schemas.Order', new Set())).toBeNull();
  });
});
