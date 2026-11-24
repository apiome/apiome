/**
 * Changelog reads (CTG-3.2, #4476), bounded for DBP-1.27 (#7210).
 *
 * Before, three surfaces read `version_changelogs.changelog_json` in bulk: the project and compare
 * pages loaded the full payload of 50 versions to read a severity, the changelog page loaded up to
 * 500 and filtered them in JavaScript, and the feeds rendered and hashed 50 before they could
 * answer `304`. Now:
 *
 *   - {@link getChangelogPage} — one statement for the changelog page: one page of versions
 *     (keyset by version, {@link CHANGELOG_PAGE_SIZE} per page), the `severity` / `pathGroup` /
 *     `since` filters applied in SQL, and the two option lists of the filter form;
 *   - {@link getChangelogPair} — the one row the compare page shows chips for, without entries;
 *   - {@link getFeedValidator} — one small aggregate a feed derives its ETag from, so an unchanged
 *     feed answers `304` without reading a payload; {@link getFeedRows} when it did change;
 *   - {@link getPublicVersionChangelog} — one version's full changelog (the Changes tab).
 *
 * All of them take a project id (from `lib/db/identity.ts`) or the slug chain, apply the public
 * gates in SQL, and throw `DatabaseUnavailableError` when the database fails.
 */

import type { PublicVersionChangelogRow, Severity } from '../changelog/types';
import { DESCRIPTION_ENTRY_CAP } from '../feed/changelog-feed';
import { mapChangelogRow, type ChangelogQueryRow } from './changelogRows';
import { LIVE_OWNER_GATES, NEWEST_VERSION_ORDER, PUBLIC_VERSION_ROW_GATES } from './gates';
import { dbQuery } from './query';

/** Versions on one changelog page. */
export const CHANGELOG_PAGE_SIZE = 20;

/**
 * Versions of one project the changelog page can reach, newest first. Its `since` and `before`
 * selectors and its path-group list cover these; a project with more shows its newest.
 */
export const CHANGELOG_VERSION_WINDOW = 500;

/** Versions a feed lists. */
export const FEED_VERSION_LIMIT = 50;

/** Entries of a version a feed item prints; the feed statement reads no more than these. */
export const FEED_ENTRY_LIMIT = DESCRIPTION_ENTRY_CAP;

/** The filters and position of one changelog page view. */
export interface ChangelogPageRequest {
  /** Only entries of this severity. */
  severity?: Severity;
  /** Only entries in this path group. */
  pathGroup?: string;
  /** Only versions published after this version label. */
  since?: string;
  /** Page position: only versions older than this version label. */
  before?: string;
}

/** One page of a project's changelog, with what the filter form needs. */
export interface ChangelogPage {
  /** This page's versions, newest first, with their (filtered) entries. */
  rows: PublicVersionChangelogRow[];
  /** The label to pass as `before` for the next (older) page; null on the last page. */
  nextBefore: string | null;
  /** Labels of the project's versions, newest first (at most {@link CHANGELOG_VERSION_WINDOW}). */
  versionLabels: string[];
  /** Versions the `since` filter leaves, across all pages. */
  versionsInRange: number;
  /** Every path group of the classified versions in range, sorted. */
  pathGroups: string[];
  /** `since` named a version this project does not publish (it was ignored). */
  sinceNotFound: boolean;
}

/** `SELECT … FROM` of a full changelog row for a version aliased `v`. */
const CHANGELOG_ROW_SELECT = `
       SELECT v.id AS published_revision_id, v.version_id AS version_label, v.published_at,
              bl.version_id AS baseline_version_label,
              vc.max_severity, vc.status`;

/** The joins {@link CHANGELOG_ROW_SELECT} needs: the classification row and its baseline's label. */
const CHANGELOG_ROW_JOINS = `
       LEFT JOIN apiome.version_changelogs vc ON vc.published_revision_id = v.id
       LEFT JOIN apiome.versions bl ON bl.id = vc.baseline_revision_id`;

/**
 * The stored publish changelog of one published public version, entries included.
 *
 * @param tenantSlug - The organization's slug.
 * @param projectSlug - The project's slug.
 * @param versionSlug - The version's label.
 * @returns The row — with null `status` / `changelog` when the version is not classified yet — or
 *   null when the version is not public or does not exist.
 * @throws DatabaseUnavailableError When the database fails.
 */
export async function getPublicVersionChangelog(
  tenantSlug: string,
  projectSlug: string,
  versionSlug: string
): Promise<PublicVersionChangelogRow | null> {
  const result = await dbQuery<ChangelogQueryRow>(
    'getPublicVersionChangelog',
    `${CHANGELOG_ROW_SELECT}, vc.changelog_json
       FROM apiome.versions v
       JOIN apiome.projects p ON v.project_id = p.id
       JOIN apiome.tenants t ON p.tenant_id = t.id
       ${CHANGELOG_ROW_JOINS}
      WHERE t.slug = $1
        AND p.slug = $2
        AND v.version_id = $3
        AND ${PUBLIC_VERSION_ROW_GATES}
        AND ${LIVE_OWNER_GATES}`,
    [tenantSlug, projectSlug, versionSlug]
  );
  return result.rows[0] ? mapChangelogRow(result.rows[0]) : null;
}

/** The single row {@link CHANGELOG_PAGE_SQL} returns. */
interface ChangelogPageRow {
  rows: ChangelogQueryRow[];
  version_labels: string[];
  versions_in_range: number;
  path_groups: string[];
  since_not_found: boolean;
}

/**
 * One page of a project's changelog.
 *
 * `$1` project id · `$2` since label · `$3` before label · `$4` severity · `$5` path group ·
 * `$6` rows to return (one more than the page, to know whether an older page exists).
 *
 * `pv` numbers the project's public versions newest first; `since` and `before` are resolved to
 * positions in it, so the page is a range of positions — stable when a version is published while
 * a reader pages, because positions are derived from the labels in the URL on every request.
 * Entries are filtered and stripped of the `before` / `after` snapshots no page prints.
 */
export const CHANGELOG_PAGE_SQL = `
  WITH pv AS MATERIALIZED (
    SELECT v.id, v.version_id, v.published_at,
           ROW_NUMBER() OVER (ORDER BY ${NEWEST_VERSION_ORDER}) AS ord
      FROM apiome.versions v
     WHERE v.project_id = $1
       AND ${PUBLIC_VERSION_ROW_GATES}
     ORDER BY ${NEWEST_VERSION_ORDER}
     LIMIT ${CHANGELOG_VERSION_WINDOW}
  ),
  bounds AS (
    SELECT (SELECT s.ord FROM pv s WHERE s.version_id = $2::text) AS since_ord,
           (SELECT b.ord FROM pv b WHERE b.version_id = $3::text) AS before_ord
  ),
  in_range AS (
    SELECT pv.* FROM pv, bounds WHERE bounds.since_ord IS NULL OR pv.ord < bounds.since_ord
  ),
  page AS (
    SELECT r.* FROM in_range r, bounds
     WHERE bounds.before_ord IS NULL OR r.ord > bounds.before_ord
     ORDER BY r.ord
     LIMIT $6
  )
  SELECT
    (SELECT COALESCE(json_agg(json_build_object(
              'published_revision_id', pg.id,
              'version_label', pg.version_id,
              'published_at', pg.published_at,
              'baseline_version_label', bl.version_id,
              'max_severity', vc.max_severity,
              'status', vc.status,
              'changelog_json',
                CASE WHEN vc.status = 'ready' AND jsonb_typeof(vc.changelog_json -> 'entries') = 'array'
                     THEN jsonb_set(vc.changelog_json, '{entries}', COALESCE((
                            SELECT jsonb_agg(e.entry - 'before' - 'after' ORDER BY e.ord)
                              FROM jsonb_array_elements(vc.changelog_json -> 'entries')
                                   WITH ORDINALITY AS e(entry, ord)
                             WHERE ($4::text IS NULL OR e.entry ->> 'severity' = $4::text)
                               AND ($5::text IS NULL OR e.entry ->> 'pathGroup' = $5::text)
                          ), '[]'::jsonb))
                     ELSE vc.changelog_json END
            ) ORDER BY pg.ord), '[]'::json)
       FROM page pg
       LEFT JOIN apiome.version_changelogs vc ON vc.published_revision_id = pg.id
       LEFT JOIN apiome.versions bl ON bl.id = vc.baseline_revision_id) AS rows,
    (SELECT COALESCE(json_agg(pv.version_id ORDER BY pv.ord), '[]'::json) FROM pv) AS version_labels,
    (SELECT COUNT(*)::int FROM in_range) AS versions_in_range,
    (SELECT COALESCE(json_agg(g.path_group ORDER BY g.path_group), '[]'::json)
       FROM (SELECT DISTINCT e.entry ->> 'pathGroup' AS path_group
               FROM in_range r
               JOIN apiome.version_changelogs vc
                 ON vc.published_revision_id = r.id AND vc.status = 'ready'
              CROSS JOIN LATERAL jsonb_array_elements(
                      CASE WHEN jsonb_typeof(vc.changelog_json -> 'entries') = 'array'
                           THEN vc.changelog_json -> 'entries' ELSE '[]'::jsonb END) AS e(entry)
              WHERE e.entry ->> 'pathGroup' IS NOT NULL) g) AS path_groups,
    ($2::text IS NOT NULL AND (SELECT since_ord FROM bounds) IS NULL) AS since_not_found`;

/**
 * One page of a project's changelog, filtered in SQL.
 *
 * @param projectId - The project's id.
 * @param request - Filters and page position.
 * @param pageSize - Versions per page.
 * @returns The page.
 * @throws DatabaseUnavailableError When the database fails.
 */
export async function getChangelogPage(
  projectId: string,
  request: ChangelogPageRequest = {},
  pageSize: number = CHANGELOG_PAGE_SIZE
): Promise<ChangelogPage> {
  const result = await dbQuery<ChangelogPageRow>('getChangelogPage', CHANGELOG_PAGE_SQL, [
    projectId,
    request.since ?? null,
    request.before ?? null,
    request.severity ?? null,
    request.pathGroup ?? null,
    pageSize + 1,
  ]);
  const row = result.rows[0];
  const all = (row?.rows ?? []).map((r) => mapChangelogRow(r));
  const rows = all.slice(0, pageSize);
  return {
    rows,
    nextBefore: all.length > pageSize ? (rows[rows.length - 1]?.versionLabel ?? null) : null,
    versionLabels: row?.version_labels ?? [],
    versionsInRange: row?.versions_in_range ?? 0,
    pathGroups: row?.path_groups ?? [],
    sinceNotFound: row?.since_not_found ?? false,
  };
}

/**
 * The stored changelog between two versions of a project — the row whose version is `head` and
 * whose baseline is `base` — without its entries (the compare page shows counts and severity).
 *
 * @param projectId - The project's id.
 * @param base - The older version's label.
 * @param head - The newer version's label.
 * @returns The row, or null when no stored changelog compares exactly these two versions.
 * @throws DatabaseUnavailableError When the database fails.
 */
export async function getChangelogPair(
  projectId: string,
  base: string,
  head: string
): Promise<PublicVersionChangelogRow | null> {
  const result = await dbQuery<ChangelogQueryRow>(
    'getChangelogPair',
    `${CHANGELOG_ROW_SELECT}, vc.changelog_json - 'entries' AS changelog_json
       FROM apiome.versions v
       JOIN apiome.version_changelogs vc ON vc.published_revision_id = v.id
       JOIN apiome.versions bl ON bl.id = vc.baseline_revision_id
      WHERE v.project_id = $1
        AND v.version_id = $3
        AND bl.version_id = $2
        AND ${PUBLIC_VERSION_ROW_GATES}
      LIMIT 1`,
    [projectId, base, head]
  );
  return result.rows[0] ? mapChangelogRow(result.rows[0], true) : null;
}

/** What a feed's ETag is derived from: it changes whenever the feed's content can. */
export interface FeedValidator {
  projectId: string;
  projectName: string;
  /** Published public versions of the project. */
  versionCount: number;
  /** The newest `updated_at` among those versions and their changelog rows, as ISO text. */
  changedAt: string | null;
}

/**
 * The cheap read a conditional feed request needs: the project's name, how many public versions it
 * has, and when any of them (or its stored changelog) last changed. No changelog payload is read.
 *
 * A version's label, publish date and visibility live on `versions`, and every writer of that row
 * sets `updated_at`; a (re)classification sets `version_changelogs.updated_at`; a deleted or
 * unpublished version changes the count. The project's name is part of the result.
 *
 * @param tenantSlug - The organization's slug.
 * @param projectSlug - The project's slug.
 * @returns The validator, or null when the project is not public or does not exist.
 * @throws DatabaseUnavailableError When the database fails.
 */
export async function getFeedValidator(tenantSlug: string, projectSlug: string): Promise<FeedValidator | null> {
  const result = await dbQuery<{
    project_id: string;
    project_name: string;
    version_count: number;
    changed_at: string | null;
  }>(
    'getFeedValidator',
    `SELECT p.id AS project_id, p.name AS project_name,
            COUNT(v.id)::int AS version_count,
            to_char(MAX(GREATEST(v.updated_at, vc.updated_at, v.published_at)) AT TIME ZONE 'UTC',
                    'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS changed_at
       FROM apiome.tenants t
       JOIN apiome.projects p ON p.tenant_id = t.id
       JOIN apiome.browse_public_projects b ON b.project_id = p.id
       JOIN apiome.versions v ON v.project_id = p.id AND ${PUBLIC_VERSION_ROW_GATES}
       LEFT JOIN apiome.version_changelogs vc ON vc.published_revision_id = v.id
      WHERE t.slug = $1
        AND p.slug = $2
        AND ${LIVE_OWNER_GATES}
      GROUP BY p.id, p.name`,
    [tenantSlug, projectSlug]
  );
  const row = result.rows[0];
  if (!row) return null;
  return {
    projectId: row.project_id,
    projectName: row.project_name,
    versionCount: row.version_count,
    changedAt: row.changed_at,
  };
}

/**
 * The rows a feed renders: the newest {@link FEED_VERSION_LIMIT} versions, each with the first
 * {@link FEED_ENTRY_LIMIT} entries of its changelog (all a feed item prints; `counts` still gives
 * the totals).
 *
 * @param projectId - The project's id (from {@link getFeedValidator}).
 * @returns The rows, newest first.
 * @throws DatabaseUnavailableError When the database fails.
 */
export async function getFeedRows(projectId: string): Promise<PublicVersionChangelogRow[]> {
  const result = await dbQuery<ChangelogQueryRow>(
    'getFeedRows',
    `${CHANGELOG_ROW_SELECT},
              CASE WHEN jsonb_typeof(vc.changelog_json -> 'entries') = 'array'
                   THEN jsonb_set(vc.changelog_json, '{entries}',
                          jsonb_path_query_array(vc.changelog_json -> 'entries', '$[0 to ${FEED_ENTRY_LIMIT - 1}]'))
                   ELSE vc.changelog_json END AS changelog_json
       FROM apiome.versions v
       ${CHANGELOG_ROW_JOINS}
      WHERE v.project_id = $1
        AND ${PUBLIC_VERSION_ROW_GATES}
      ORDER BY ${NEWEST_VERSION_ORDER}
      LIMIT ${FEED_VERSION_LIMIT}`,
    [projectId]
  );
  return result.rows.map((row) => mapChangelogRow(row));
}
