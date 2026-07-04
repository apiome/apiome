import {
  compareProjectsDashboardRows,
  sortProjectsDashboardRows,
  type ProjectSortRow,
} from '@/app/utils/projects-dashboard-sort';

const base = (over: Partial<ProjectSortRow>): ProjectSortRow => ({
  id: over.id ?? '1',
  name: over.name ?? 'Alpha',
  description: over.description ?? '',
  enabled: over.enabled ?? true,
  deleted_at: over.deleted_at ?? null,
  created_at: over.created_at ?? '2024-01-02T00:00:00.000Z',
  updated_at: over.updated_at ?? '2024-01-03T00:00:00.000Z',
  creator_name: over.creator_name ?? 'Alice',
  creator_email: over.creator_email ?? 'a@x.com',
  metadata: over.metadata,
  slug: over.slug,
  versionsCount: over.versionsCount,
});

describe('compareProjectsDashboardRows', () => {
  it('sorts by name case-insensitively with slug tie-breaker', () => {
    const a = base({ name: 'b', slug: 'z' });
    const b = base({ name: 'a', slug: 'y' });
    expect(compareProjectsDashboardRows(a, b, 'name', 'asc', null, null)).toBeGreaterThan(0);
    expect(compareProjectsDashboardRows(b, a, 'name', 'asc', null, null)).toBeLessThan(0);
    const sameNameA = base({ id: '1', name: 'Same', slug: 'a' });
    const sameNameB = base({ id: '2', name: 'Same', slug: 'b' });
    expect(compareProjectsDashboardRows(sameNameA, sameNameB, 'name', 'asc', null, null)).toBeLessThan(0);
  });

  it('sorts by description including metadata summary', () => {
    const a = base({ description: 'zebra', metadata: { summary: '' } });
    const b = base({ description: 'apple', metadata: { summary: 'x' } });
    expect(compareProjectsDashboardRows(a, b, 'description', 'asc', null, null)).toBeGreaterThan(0);
  });

  it('puts missing quality scores last regardless of direction', () => {
    const a = base({ id: 'a' });
    const b = base({ id: 'b' });
    expect(compareProjectsDashboardRows(a, b, 'quality', 'asc', null, 50)).toBeGreaterThan(0);
    expect(compareProjectsDashboardRows(a, b, 'quality', 'desc', null, 50)).toBeGreaterThan(0);
    expect(compareProjectsDashboardRows(a, b, 'quality', 'asc', 10, 50)).toBeLessThan(0);
    expect(compareProjectsDashboardRows(b, a, 'quality', 'desc', 50, 10)).toBeLessThan(0);
  });

  it('sorts by versionsCount', () => {
    const few = base({ id: 'a', versionsCount: 2 });
    const many = base({ id: 'b', versionsCount: 11 });
    const empty = base({ id: 'c', versionsCount: 0 });
    expect(compareProjectsDashboardRows(few, many, 'versions', 'asc', null, null)).toBeLessThan(0);
    expect(compareProjectsDashboardRows(few, many, 'versions', 'desc', null, null)).toBeGreaterThan(0);
    expect(compareProjectsDashboardRows(empty, few, 'versions', 'asc', null, null)).toBeLessThan(0);
  });

  it('sorts by status tier then name', () => {
    const active = base({ id: '1', name: 'Z', enabled: true, deleted_at: null });
    const disabled = base({ id: '2', name: 'A', enabled: false, deleted_at: null });
    expect(compareProjectsDashboardRows(active, disabled, 'status', 'asc', null, null)).toBeLessThan(0);
    const deleted = base({ id: '3', name: 'A', enabled: true, deleted_at: '2024-01-01' });
    expect(compareProjectsDashboardRows(active, deleted, 'status', 'asc', null, null)).toBeLessThan(0);
  });

  it('sorts by creator then email', () => {
    const a = base({ creator_name: 'Bob', creator_email: 'b@z.com' });
    const b = base({ creator_name: 'Bob', creator_email: 'a@z.com' });
    expect(compareProjectsDashboardRows(a, b, 'creator', 'asc', null, null)).toBeGreaterThan(0);
  });

  it('sorts by created_at', () => {
    const older = base({ created_at: '2020-01-01T00:00:00.000Z' });
    const newer = base({ created_at: '2021-01-01T00:00:00.000Z' });
    expect(compareProjectsDashboardRows(older, newer, 'created', 'asc', null, null)).toBeLessThan(0);
    expect(compareProjectsDashboardRows(older, newer, 'created', 'desc', null, null)).toBeGreaterThan(0);
  });
});

describe('sortProjectsDashboardRows', () => {
  it('returns a shallow copy stable when column is null', () => {
    const rows = [base({ id: '2', name: 'B' }), base({ id: '1', name: 'A' })];
    const out = sortProjectsDashboardRows(rows, null, 'asc', {});
    expect(out).not.toBe(rows);
    expect(out.map((r) => r.id)).toEqual(['2', '1']);
  });

  it('sorts full list by updated', () => {
    const rows = [
      base({ id: 'a', name: 'x', updated_at: '2024-06-01T00:00:00.000Z' }),
      base({ id: 'b', name: 'y', updated_at: '2024-01-01T00:00:00.000Z' }),
    ];
    const out = sortProjectsDashboardRows(rows, 'updated', 'asc', {});
    expect(out.map((r) => r.id)).toEqual(['b', 'a']);
  });
});
