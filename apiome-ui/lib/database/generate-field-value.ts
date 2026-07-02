/**
 * Generate field values for UUID and timestamp in the insert form.
 * UUID versions: v1 (time-based), v4 (random). v7 is not available in this uuid build so we use v4.
 */

import { v1, v4 } from 'uuid';

export type UuidVersion = 1 | 4 | 7;

export function generateUuid(version: UuidVersion): string {
  switch (version) {
    case 1:
      return v1();
    case 4:
    case 7:
      // v7 not exported by uuid ESM build in this environment; use v4
      return v4();
    default:
      return v4();
  }
}

export type TimestampDefaultKind = 'CURRENT_TIMESTAMP' | 'NOW()' | 'iso' | null;

/** Generate a timestamp string from the given kind (e.g. CURRENT_TIMESTAMP → current time in ISO 8601). */
export function generateTimestamp(kind: TimestampDefaultKind): string {
  const now = new Date();
  return now.toISOString();
}
