/**
 * Per-file refresh state machine — TypeScript port for the Specs tab (RAR-5.1, #3532).
 *
 * The REST read model materializes `refresh_status` server-side
 * (apiome-rest `repository_refresh_status.compute_refresh_status` +
 * `repository_refresh_comparator.evaluate_refresh`). The repository detail UI,
 * however, sources the per-file refresh signals directly from Postgres through
 * its own DAO (`repository-import-metrics.ts`) rather than proxying the Python
 * read endpoint, so the status must be derived here.
 *
 * This module is a faithful, behaviour-preserving port of those two pure Python
 * functions: given the same recency anchors and operational flags it returns the
 * same `RefreshStatusCode` the REST read model would. Keeping it pure (no React,
 * no I/O) means it is unit-testable in isolation and the parity with the Python
 * fixtures can be asserted directly.
 *
 * The resulting code maps to a label/tone/tooltip via
 * `repository-refresh-status-chip-copy.ts`.
 */

import type { RefreshStatusCode } from './repository-refresh-status-chip-copy';

/** A committed-at timestamp as it arrives over the wire (ISO-8601) or absent. */
export type TimestampInput = string | Date | null | undefined;

/**
 * Coerce a committed-at value to epoch milliseconds, or `null` when it is absent
 * or unparseable. Mirrors the Python comparator's `_parse_timestamp`: a missing
 * or malformed timestamp drops the decision onto the checksum-only fallback
 * rather than throwing. ISO-8601 strings (including the trailing `Z` UTC
 * designator returned by the GitHub branch API) are accepted via `Date.parse`.
 *
 * @param value A `Date`, an ISO-8601 string, or null/undefined.
 * @returns Epoch milliseconds, or null when the value cannot be parsed.
 */
function parseTimestamp(value: TimestampInput): number | null {
  if (value == null) return null;
  if (value instanceof Date) {
    const t = value.getTime();
    return Number.isNaN(t) ? null : t;
  }
  const trimmed = String(value).trim();
  if (!trimmed) return null;
  const t = Date.parse(trimmed);
  return Number.isNaN(t) ? null : t;
}

/**
 * Trim a content-identity token (blob SHA / checksum) to a comparable form,
 * collapsing blank strings to `null` so two "unknown" sides compare equal.
 * Mirrors the Python comparator's `_normalise_checksum`.
 *
 * @param value A blob SHA / checksum, possibly blank or absent.
 * @returns The trimmed token, or null when blank/absent.
 */
function normaliseChecksum(value: string | null | undefined): string | null {
  if (value == null) return null;
  const trimmed = value.trim();
  return trimmed || null;
}

/** Inputs to the recency comparator (RAR-2.2 parity). */
export interface RefreshRecencyInput {
  /** Committed-at of the current remote file (scan recency signal). */
  remoteCommittedAt?: TimestampInput;
  /** Stored `last_imported_committed_at` anchor (RAR-2.1). */
  lastImportedCommittedAt?: TimestampInput;
  /** Current remote content identity (blob SHA / checksum). */
  remoteChecksum?: string | null;
  /** Stored `last_imported_blob_sha` / checksum anchor (RAR-2.1). */
  lastImportedChecksum?: string | null;
}

/**
 * Decide whether a file is newer-than its import anchor and therefore due for a
 * re-import. A faithful port of the Python `evaluate_refresh` (RAR-2.2): the
 * decision gates on commit recency, not raw checksum drift, so reverting a file
 * to older content does not pull a stale spec.
 *
 * Decision table (mirrors the roadmap):
 * - No prior anchor at all (timestamp and checksum both absent) → refresh.
 * - Both committed-at timestamps parse → authoritative comparison:
 *   - remote strictly newer + content differs → refresh.
 *   - remote strictly newer + content identical → skip (idempotent).
 *   - remote older/equal → skip (stale guard).
 * - Either timestamp missing/unparseable → checksum fallback: refresh iff the
 *   content identity changed.
 *
 * @param input The remote vs anchored recency signals.
 * @returns True when the file should be re-imported (i.e. is "stale").
 */
export function shouldRefresh(input: RefreshRecencyInput): boolean {
  const remoteTs = parseTimestamp(input.remoteCommittedAt);
  const lastTs = parseTimestamp(input.lastImportedCommittedAt);
  const remoteSum = normaliseChecksum(input.remoteChecksum);
  const lastSum = normaliseChecksum(input.lastImportedChecksum);

  // Nothing recorded for this lineage: no anchor to be "newer than", so treat as
  // a first import and proceed.
  if (lastTs === null && lastSum === null) {
    return true;
  }

  const contentDiffers = remoteSum !== lastSum;

  // Authoritative path: both timestamps comparable.
  if (remoteTs !== null && lastTs !== null) {
    if (remoteTs > lastTs) {
      return contentDiffers;
    }
    // Older or equal commit timestamp: never pull it (stale guard).
    return false;
  }

  // Fallback: no comparable timestamp → legacy checksum-changed gating.
  return contentDiffers;
}

/** Operational signals overlaid on the recency axis (RAR-2.3). */
export interface RefreshOperationalInput {
  /** True when a refresh is currently enqueued/running for the file. */
  isRefreshing?: boolean;
  /** True when the most recent refresh attempt errored and has not since succeeded. */
  lastRefreshFailed?: boolean;
  /** True when the imported version was hand-edited after import (RAR-4.4) and held for review. */
  diverged?: boolean;
}

export type RefreshStatusInput = RefreshRecencyInput & RefreshOperationalInput;

/**
 * Materialize the per-file refresh status (RAR-2.3). A faithful port of the
 * Python `compute_refresh_status`: it combines the operational axis (supplied by
 * sweep/refresh bookkeeping) with the derived recency axis, with operational
 * signals taking precedence because they describe an actual refresh attempt
 * rather than a mere comparison.
 *
 * Precedence (highest first), mirroring the state diagram:
 * 1. `isRefreshing`      → `refreshing` (in flight)
 * 2. `diverged`          → `diverged` (safety hold; outranks failed so a content
 *    hold is never masked by a transient error)
 * 3. `lastRefreshFailed` → `failed` (awaiting retry)
 * 4. comparator says refresh → `stale`
 * 5. otherwise           → `up-to-date`
 *
 * @param input The recency anchors plus operational flags.
 * @returns The single `RefreshStatusCode` for the file.
 */
export function computeRefreshStatus(input: RefreshStatusInput): RefreshStatusCode {
  if (input.isRefreshing) return 'refreshing';
  if (input.diverged) return 'diverged';
  if (input.lastRefreshFailed) return 'failed';
  return shouldRefresh(input) ? 'stale' : 'up-to-date';
}

/**
 * Compute the next scheduled auto-refresh time for a repository file from the
 * per-repo cadence (RAR-3.1). The sweep selects a repository when
 * `last_refreshed_at IS NULL OR now() - last_refreshed_at >= refresh_interval`,
 * so the next due moment is the last sweep tick plus the interval. A repository
 * that has never been swept (`repoLastRefreshedAt` null) is due immediately.
 *
 * @param repoLastRefreshedAt The repository's `last_refreshed_at` sweep anchor.
 * @param refreshIntervalSeconds The per-repo cadence in seconds.
 * @param autoRefreshEnabled Whether auto-refresh is enabled for the repository.
 * @returns The next-due `Date`, `'due'` when already due / never swept, or
 *   `null` when auto-refresh is disabled (no next-due to show).
 */
export function computeNextDue(
  repoLastRefreshedAt: TimestampInput,
  refreshIntervalSeconds: number | null | undefined,
  autoRefreshEnabled: boolean,
): Date | 'due' | null {
  if (!autoRefreshEnabled) return null;
  const last = parseTimestamp(repoLastRefreshedAt);
  if (last === null) return 'due';
  const intervalMs = Math.max(0, (refreshIntervalSeconds ?? 0)) * 1000;
  return new Date(last + intervalMs);
}
