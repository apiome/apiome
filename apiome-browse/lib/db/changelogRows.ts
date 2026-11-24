/**
 * The shape shared by every changelog read (CTG-3.2, #4476; split out for DBP-1.27, #7210).
 *
 * The private `error` column of `version_changelogs` is never selected — a failed row surfaces
 * publicly only as `status = 'failed'`.
 */

import type {
  ChangelogPayload,
  ChangelogStatus,
  PublicVersionChangelogRow,
  Severity,
} from '../changelog/types';

/** A changelog row as the statements in `lib/db` select it (snake_case). */
export interface ChangelogQueryRow {
  published_revision_id: string;
  version_label: string;
  published_at: string | Date | null;
  baseline_version_label: string | null;
  max_severity: string | null;
  status: string | null;
  changelog_json: unknown;
}

/**
 * Map one changelog query row to the public camelCase shape.
 *
 * @param row - The row.
 * @param entriesOmitted - The statement left the payload's entries out (a summary read). The
 *   payload then carries an empty `entries` list and the row is marked, so a reader can tell
 *   "no changes" from "not loaded".
 * @returns The public row.
 */
export function mapChangelogRow(row: ChangelogQueryRow, entriesOmitted = false): PublicVersionChangelogRow {
  const payload = (row.changelog_json as ChangelogPayload | null) ?? null;
  const publishedAt =
    typeof row.published_at === 'string' ? new Date(row.published_at) : row.published_at;
  return {
    publishedRevisionId: row.published_revision_id,
    versionLabel: row.version_label,
    publishedAt: publishedAt instanceof Date && Number.isNaN(publishedAt.getTime()) ? null : publishedAt,
    baselineVersionLabel: row.baseline_version_label,
    maxSeverity: (row.max_severity as Severity | null) ?? null,
    status: (row.status as ChangelogStatus | null) ?? null,
    changelog: payload && entriesOmitted ? { ...payload, entries: [] } : payload,
    ...(payload && entriesOmitted ? { entriesOmitted: true as const } : {}),
  };
}
