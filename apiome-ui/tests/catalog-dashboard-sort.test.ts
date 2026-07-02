/**
 * Unit tests for the Catalog dashboard sorter (MFI-23.3, #4012).
 *
 * Mirrors the Projects sorter's behaviour (stable, "unknowns last") and exercises the catalog-only
 * `grade` and `format` columns plus the shared name/description/quality/status/creator/created/
 * updated columns, in both directions.
 */

import {
  sortCatalogDashboardRows,
  compareCatalogDashboardRows,
  type CatalogSortRow,
} from '@/app/utils/catalog-dashboard-sort';

function row(partial: Partial<CatalogSortRow> & { id: string; name: string }): CatalogSortRow {
  return {
    enabled: true,
    deleted_at: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    creator_name: 'Ada Lovelace',
    creator_email: 'ada@example.com',
    description: '',
    slug: partial.name.toLowerCase(),
    ...partial,
  };
}

const names = (rows: CatalogSortRow[]) => rows.map((r) => r.name);

describe('sortCatalogDashboardRows', () => {
  it('returns a new array and does not mutate the input', () => {
    const input = [row({ id: '2', name: 'Beta' }), row({ id: '1', name: 'Alpha' })];
    const snapshot = names(input);
    const out = sortCatalogDashboardRows(input, 'name', 'asc');
    expect(out).not.toBe(input);
    expect(names(input)).toEqual(snapshot); // input untouched
    expect(names(out)).toEqual(['Alpha', 'Beta']);
  });

  it('leaves order untouched when column is null', () => {
    const input = [row({ id: '2', name: 'Beta' }), row({ id: '1', name: 'Alpha' })];
    expect(names(sortCatalogDashboardRows(input, null, 'asc'))).toEqual(['Beta', 'Alpha']);
  });

  it('sorts by name case-insensitively and respects direction', () => {
    const input = [
      row({ id: '1', name: 'gamma' }),
      row({ id: '2', name: 'Alpha' }),
      row({ id: '3', name: 'beta' }),
    ];
    expect(names(sortCatalogDashboardRows(input, 'name', 'asc'))).toEqual(['Alpha', 'beta', 'gamma']);
    expect(names(sortCatalogDashboardRows(input, 'name', 'desc'))).toEqual(['gamma', 'beta', 'Alpha']);
  });

  it('breaks name ties by slug', () => {
    const input = [
      row({ id: '1', name: 'Same', slug: 'zeta' }),
      row({ id: '2', name: 'Same', slug: 'alpha' }),
    ];
    expect(sortCatalogDashboardRows(input, 'name', 'asc').map((r) => r.slug)).toEqual(['alpha', 'zeta']);
  });
});

describe('quality column', () => {
  it('orders by score with nulls always last regardless of direction', () => {
    const input = [
      row({ id: '1', name: 'A', qualityScore: 50 }),
      row({ id: '2', name: 'B', qualityScore: null }),
      row({ id: '3', name: 'C', qualityScore: 90 }),
    ];
    expect(names(sortCatalogDashboardRows(input, 'quality', 'asc'))).toEqual(['A', 'C', 'B']);
    expect(names(sortCatalogDashboardRows(input, 'quality', 'desc'))).toEqual(['C', 'A', 'B']);
  });
});

describe('grade column', () => {
  it('orders letter grades alphabetically with blanks last', () => {
    const input = [
      row({ id: '1', name: 'A', qualityGrade: 'B' }),
      row({ id: '2', name: 'B', qualityGrade: null }),
      row({ id: '3', name: 'C', qualityGrade: 'A' }),
    ];
    expect(names(sortCatalogDashboardRows(input, 'grade', 'asc'))).toEqual(['C', 'A', 'B']);
    expect(names(sortCatalogDashboardRows(input, 'grade', 'desc'))).toEqual(['A', 'C', 'B']);
  });
});

describe('format column', () => {
  it('orders by sourceFormat with unknown formats last', () => {
    const input = [
      row({ id: '1', name: 'A', sourceFormat: 'graphql' }),
      row({ id: '2', name: 'B', sourceFormat: null }),
      row({ id: '3', name: 'C', sourceFormat: 'asyncapi' }),
    ];
    expect(names(sortCatalogDashboardRows(input, 'format', 'asc'))).toEqual(['C', 'A', 'B']);
    expect(names(sortCatalogDashboardRows(input, 'format', 'desc'))).toEqual(['A', 'C', 'B']);
  });

  it('breaks format ties by protocol', () => {
    const input = [
      row({ id: '1', name: 'A', sourceFormat: 'asyncapi', protocol: 'mqtt' }),
      row({ id: '2', name: 'B', sourceFormat: 'asyncapi', protocol: 'amqp' }),
    ];
    expect(names(sortCatalogDashboardRows(input, 'format', 'asc'))).toEqual(['B', 'A']);
  });

  it('falls back to protocol when both formats are unknown', () => {
    const input = [
      row({ id: '1', name: 'A', sourceFormat: null, protocol: 'mqtt' }),
      row({ id: '2', name: 'B', sourceFormat: null, protocol: 'amqp' }),
    ];
    expect(names(sortCatalogDashboardRows(input, 'format', 'asc'))).toEqual(['B', 'A']);
  });
});

describe('status column', () => {
  it('orders active < disabled < deleted', () => {
    const input = [
      row({ id: '1', name: 'Deleted', deleted_at: '2026-02-01T00:00:00Z' }),
      row({ id: '2', name: 'Disabled', enabled: false }),
      row({ id: '3', name: 'Active', enabled: true }),
    ];
    expect(names(sortCatalogDashboardRows(input, 'status', 'asc'))).toEqual(['Active', 'Disabled', 'Deleted']);
  });
});

describe('created / updated columns', () => {
  it('orders by timestamp ascending and descending', () => {
    const input = [
      row({ id: '1', name: 'Mid', created_at: '2026-03-01T00:00:00Z' }),
      row({ id: '2', name: 'Old', created_at: '2026-01-01T00:00:00Z' }),
      row({ id: '3', name: 'New', created_at: '2026-06-01T00:00:00Z' }),
    ];
    expect(names(sortCatalogDashboardRows(input, 'created', 'asc'))).toEqual(['Old', 'Mid', 'New']);
    expect(names(sortCatalogDashboardRows(input, 'created', 'desc'))).toEqual(['New', 'Mid', 'Old']);
  });

  it('puts unparseable dates last', () => {
    const input = [
      row({ id: '1', name: 'Bad', updated_at: 'not-a-date' }),
      row({ id: '2', name: 'Good', updated_at: '2026-01-01T00:00:00Z' }),
    ];
    expect(names(sortCatalogDashboardRows(input, 'updated', 'asc'))).toEqual(['Good', 'Bad']);
    expect(names(sortCatalogDashboardRows(input, 'updated', 'desc'))).toEqual(['Good', 'Bad']);
  });
});

describe('creator and description columns', () => {
  it('sorts by creator name then email', () => {
    const input = [
      row({ id: '1', name: 'A', creator_name: 'Same', creator_email: 'z@example.com' }),
      row({ id: '2', name: 'B', creator_name: 'Same', creator_email: 'a@example.com' }),
    ];
    expect(names(sortCatalogDashboardRows(input, 'creator', 'asc'))).toEqual(['B', 'A']);
  });

  it('sorts by description, folding in the metadata summary', () => {
    const input = [
      row({ id: '1', name: 'A', description: 'zebra' }),
      row({ id: '2', name: 'B', description: '', metadata: { summary: 'apple' } }),
    ];
    expect(names(sortCatalogDashboardRows(input, 'description', 'asc'))).toEqual(['B', 'A']);
  });
});

describe('compareCatalogDashboardRows', () => {
  it('treats equal rows as 0 for an unknown column (default branch)', () => {
    const a = row({ id: '1', name: 'A' });
    const b = row({ id: '2', name: 'B' });
    // @ts-expect-error — exercising the defensive default branch with an invalid column.
    expect(compareCatalogDashboardRows(a, b, 'nope', 'asc')).toBe(0);
  });
});
