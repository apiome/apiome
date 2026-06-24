/**
 * Retention policy for backups.
 *
 * A policy is two independent guards, both optional:
 *   - keepDays:  delete backups older than N days.
 *   - keepLast:  always keep the N most-recent backups regardless of age.
 *
 * The two compose conservatively: a backup is pruned only when it is BOTH older than `keepDays`
 * AND not among the `keepLast` most recent. That ordering means a quiet system that takes one
 * backup a week never prunes its only good copies just because they aged out. With neither guard
 * set, nothing is ever pruned (a deliberate, safe default).
 */

import { CliError } from "../errors.js";

export type RetentionPolicy = {
  /** Delete backups strictly older than this many days. Undefined disables the age guard. */
  keepDays?: number;
  /** Always keep this many most-recent backups. Undefined disables the count guard. */
  keepLast?: number;
};

/** Default policy mirrored in the docs/runbook: 30-day window, never drop below 7 copies. */
export const DEFAULT_RETENTION: RetentionPolicy = { keepDays: 30, keepLast: 7 };

/** Parse a positive-integer option (keep-days / keep-last); undefined passes through. */
export function parseCount(value: string | undefined, label: string): number | undefined {
  if (value === undefined) return undefined;
  const n = Number(value);
  if (!Number.isInteger(n) || n < 0) {
    throw new CliError(`${label} must be a non-negative integer (got "${value}").`);
  }
  return n;
}

/** A minimal view of a backup needed for retention decisions. */
export type Retainable = {
  id: string;
  /** ISO 8601 creation timestamp. */
  createdAt: string;
};

/**
 * Decide which backups to prune under `policy` as of `now`.
 *
 * Returns the items to delete (the complement is what is kept). Backups are evaluated newest
 * first; the `keepLast` newest are always retained, and of the remainder only those older than
 * `keepDays` are pruned. Items with an unparseable `createdAt` are never pruned (fail safe).
 */
export function selectExpired<T extends Retainable>(
  backups: T[],
  policy: RetentionPolicy,
  now: Date,
): T[] {
  if (policy.keepDays === undefined && policy.keepLast === undefined) {
    return [];
  }
  // Newest first so index < keepLast identifies the protected, most-recent copies.
  const ordered = [...backups].sort((a, b) => b.createdAt.localeCompare(a.createdAt));
  const cutoffMs =
    policy.keepDays === undefined ? null : now.getTime() - policy.keepDays * 24 * 60 * 60 * 1000;

  const expired: T[] = [];
  ordered.forEach((backup, index) => {
    if (policy.keepLast !== undefined && index < policy.keepLast) {
      return; // protected by count guard
    }
    if (cutoffMs === null) {
      return; // only a count guard is set, and this copy survived it
    }
    const createdMs = Date.parse(backup.createdAt);
    if (Number.isNaN(createdMs)) {
      return; // unparseable timestamp → never prune
    }
    if (createdMs < cutoffMs) {
      expired.push(backup);
    }
  });
  return expired;
}

/** Human-readable description of a policy for status output. */
export function describeRetention(policy: RetentionPolicy): string {
  const parts: string[] = [];
  if (policy.keepDays !== undefined) parts.push(`keep ${policy.keepDays}d`);
  if (policy.keepLast !== undefined) parts.push(`keep last ${policy.keepLast}`);
  return parts.length > 0 ? parts.join(" · ") : "retain forever";
}
