import {
  compareVersionsDashboardRows,
  sortVersionsDashboardRows,
  type VersionSortRow,
} from '@/app/utils/versions-dashboard-sort';

const base = (over: Partial<VersionSortRow>): VersionSortRow => ({
  id: over.id ?? 'rev-1',
  version_id: over.version_id ?? '1.0.0',
  shortMessage: over.shortMessage ?? null,
  changelog: over.changelog ?? null,
  message: over.message ?? null,
  published: over.published ?? false,
  enabled: over.enabled ?? true,
  lifecycle: over.lifecycle,
  creator_name: over.creator_name ?? 'Alice',
  creator_email: over.creator_email ?? 'a@x.com',
  created_at: over.created_at ?? '2024-01-02T00:00:00.000Z',
});

describe('compareVersionsDashboardRows', () => {
  it('sorts by version_id with numeric-aware ordering', () => {
    const a = base({ id: 'a', version_id: '1.10.0' });
    const b = base({ id: 'b', version_id: '1.2.0' });
    expect(compareVersionsDashboardRows(a, b, 'version', 'asc')).toBeGreaterThan(0);
    expect(compareVersionsDashboardRows(b, a, 'version', 'asc')).toBeLessThan(0);
  });

  it('sorts revision column using shortMessage, message, and changelog', () => {
    const z = base({ id: '1', shortMessage: 'zebra', message: null, changelog: null });
    const apple = base({ id: '2', shortMessage: 'apple', message: 'body', changelog: null });
    expect(compareVersionsDashboardRows(z, apple, 'revision', 'asc')).toBeGreaterThan(0);
    const withChg = base({ id: '3', shortMessage: null, message: null, changelog: 'notes' });
    const empty = base({ id: '4', shortMessage: null, message: null, changelog: null });
    expect(compareVersionsDashboardRows(empty, withChg, 'revision', 'asc')).toBeLessThan(0);
    expect(compareVersionsDashboardRows(withChg, empty, 'revision', 'asc')).toBeGreaterThan(0);
  });

  it('sorts status by draft/published and enabled before lifecycle detail', () => {
    const draftOn = base({ id: 'd', published: false, enabled: true, lifecycle: 'stable' });
    const pubOn = base({ id: 'p', published: true, enabled: true, lifecycle: 'stable' });
    expect(compareVersionsDashboardRows(draftOn, pubOn, 'status', 'asc')).toBeLessThan(0);
    const disabled = base({ id: 'x', published: false, enabled: false });
    expect(compareVersionsDashboardRows(draftOn, disabled, 'status', 'asc')).toBeLessThan(0);
  });

  it('sorts by creator then email', () => {
    const a = base({ id: '1', creator_name: 'Bob', creator_email: 'b@z.com' });
    const b = base({ id: '2', creator_name: 'Bob', creator_email: 'a@z.com' });
    expect(compareVersionsDashboardRows(a, b, 'creator', 'asc')).toBeGreaterThan(0);
  });

  it('sorts by created_at', () => {
    const older = base({ id: 'o', created_at: '2020-01-01T00:00:00.000Z' });
    const newer = base({ id: 'n', created_at: '2021-01-01T00:00:00.000Z' });
    expect(compareVersionsDashboardRows(older, newer, 'created', 'asc')).toBeLessThan(0);
    expect(compareVersionsDashboardRows(older, newer, 'created', 'desc')).toBeGreaterThan(0);
  });
});

describe('sortVersionsDashboardRows', () => {
  it('returns a copy preserving order when column is null', () => {
    const rows = [base({ id: '2', version_id: '2.0.0' }), base({ id: '1', version_id: '1.0.0' })];
    const out = sortVersionsDashboardRows(rows, null, 'asc');
    expect(out).not.toBe(rows);
    expect(out.map((r) => r.id)).toEqual(['2', '1']);
  });

  it('sorts full list by version ascending', () => {
    const rows = [
      base({ id: 'b', version_id: '10.0.0' }),
      base({ id: 'a', version_id: '2.0.0' }),
    ];
    const out = sortVersionsDashboardRows(rows, 'version', 'asc');
    expect(out.map((r) => r.id)).toEqual(['a', 'b']);
  });
});
