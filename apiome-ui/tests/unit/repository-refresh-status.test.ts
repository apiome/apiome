/**
 * TypeScript-port parity tests for the per-file refresh state machine
 * (RAR-5.1, #3532).
 *
 * Mirrors the apiome-rest fixtures for
 * `repository_refresh_comparator.evaluate_refresh` (RAR-2.2) and
 * `repository_refresh_status.compute_refresh_status` (RAR-2.3) so the client port
 * cannot drift from the server's materialized `refresh_status`.
 */

import {
  computeNextDue,
  computeRefreshStatus,
  shouldRefresh,
} from '@/app/components/ade/dashboard/repositories/repository-refresh-status';

const T0 = '2026-06-01T00:00:00Z';
const T1 = '2026-06-02T00:00:00Z'; // strictly newer than T0

describe('shouldRefresh (RAR-2.2 comparator parity)', () => {
  test('no prior anchor at all → refresh (first import)', () => {
    expect(
      shouldRefresh({
        remoteCommittedAt: T1,
        lastImportedCommittedAt: null,
        remoteChecksum: 'b1',
        lastImportedChecksum: null,
      }),
    ).toBe(true);
  });

  test('newer commit + changed content → refresh', () => {
    expect(
      shouldRefresh({
        remoteCommittedAt: T1,
        lastImportedCommittedAt: T0,
        remoteChecksum: 'b2',
        lastImportedChecksum: 'b1',
      }),
    ).toBe(true);
  });

  test('newer commit + identical content → skip (idempotent)', () => {
    expect(
      shouldRefresh({
        remoteCommittedAt: T1,
        lastImportedCommittedAt: T0,
        remoteChecksum: 'b1',
        lastImportedChecksum: 'b1',
      }),
    ).toBe(false);
  });

  test('older/equal commit timestamp → skip (stale guard, even if checksum differs)', () => {
    // Reverting to older content yields a different checksum but an older commit.
    expect(
      shouldRefresh({
        remoteCommittedAt: T0,
        lastImportedCommittedAt: T1,
        remoteChecksum: 'b-old',
        lastImportedChecksum: 'b-new',
      }),
    ).toBe(false);
    // Equal timestamp is also a skip.
    expect(
      shouldRefresh({
        remoteCommittedAt: T0,
        lastImportedCommittedAt: T0,
        remoteChecksum: 'b2',
        lastImportedChecksum: 'b1',
      }),
    ).toBe(false);
  });

  test('missing/unparseable timestamp → checksum fallback', () => {
    // Changed content with no comparable timestamp → refresh.
    expect(
      shouldRefresh({
        remoteCommittedAt: null,
        lastImportedCommittedAt: T0,
        remoteChecksum: 'b2',
        lastImportedChecksum: 'b1',
      }),
    ).toBe(true);
    // Identical content with no comparable timestamp → skip.
    expect(
      shouldRefresh({
        remoteCommittedAt: 'not-a-date',
        lastImportedCommittedAt: T0,
        remoteChecksum: 'b1',
        lastImportedChecksum: 'b1',
      }),
    ).toBe(false);
  });

  test('blank checksums compare equal', () => {
    expect(
      shouldRefresh({
        remoteCommittedAt: null,
        lastImportedCommittedAt: T0,
        remoteChecksum: '   ',
        lastImportedChecksum: '',
      }),
    ).toBe(false);
  });
});

describe('computeRefreshStatus (RAR-2.3 precedence parity)', () => {
  const stale = {
    remoteCommittedAt: T1,
    lastImportedCommittedAt: T0,
    remoteChecksum: 'b2',
    lastImportedChecksum: 'b1',
  };

  test('up-to-date when nothing newer and no operational flags', () => {
    expect(
      computeRefreshStatus({
        remoteCommittedAt: T0,
        lastImportedCommittedAt: T0,
        remoteChecksum: 'b1',
        lastImportedChecksum: 'b1',
      }),
    ).toBe('up-to-date');
  });

  test('stale when comparator would re-import', () => {
    expect(computeRefreshStatus(stale)).toBe('stale');
  });

  test('refreshing outranks everything', () => {
    expect(
      computeRefreshStatus({ ...stale, isRefreshing: true, diverged: true, lastRefreshFailed: true }),
    ).toBe('refreshing');
  });

  test('diverged outranks failed and recency', () => {
    expect(computeRefreshStatus({ ...stale, diverged: true, lastRefreshFailed: true })).toBe(
      'diverged',
    );
  });

  test('failed outranks recency', () => {
    expect(computeRefreshStatus({ ...stale, lastRefreshFailed: true })).toBe('failed');
  });

  test('all five states are reachable', () => {
    const seen = new Set([
      computeRefreshStatus({ ...stale, isRefreshing: true }),
      computeRefreshStatus({ ...stale, diverged: true }),
      computeRefreshStatus({ ...stale, lastRefreshFailed: true }),
      computeRefreshStatus(stale),
      computeRefreshStatus({
        remoteCommittedAt: T0,
        lastImportedCommittedAt: T0,
        remoteChecksum: 'b1',
        lastImportedChecksum: 'b1',
      }),
    ]);
    expect(seen).toEqual(new Set(['refreshing', 'diverged', 'failed', 'stale', 'up-to-date']));
  });
});

describe('computeNextDue (RAR-3.1 cadence)', () => {
  const base = Date.parse('2026-06-22T12:00:00Z');

  test('null when auto-refresh disabled', () => {
    expect(computeNextDue('2026-06-22T11:00:00Z', 300, false)).toBeNull();
  });

  test("'due' when never swept", () => {
    expect(computeNextDue(null, 300, true)).toBe('due');
  });

  test('last sweep + interval when swept', () => {
    const next = computeNextDue('2026-06-22T12:00:00Z', 300, true);
    expect(next).toBeInstanceOf(Date);
    expect((next as Date).getTime()).toBe(base + 300_000);
  });

  test('treats a missing interval as zero', () => {
    const next = computeNextDue('2026-06-22T12:00:00Z', null, true);
    expect((next as Date).getTime()).toBe(base);
  });
});
