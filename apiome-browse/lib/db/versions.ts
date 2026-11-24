/**
 * Project and version reads for the project, version and compare pages (DBP-1.27, #7210).
 *
 * Each page reads what it shows and no more:
 *
 *   - the project page: the project with its latest version's card facts (through the summary
 *     table, so no "latest public version" search), then one bounded list of versions that carries
 *     each version's classified severity — the full changelog payloads it used to load for 50
 *     versions were read for one field;
 *   - the version page: **one statement** — the version, its card facts, the three sidebar fields
 *     of its sibling versions and the changelog's summary. The changelog's entries come along only
 *     when the page opens on the Changes tab; otherwise the tab fetches them when it is opened;
 *   - the compare page: version labels only.
 *
 * Every function throws `DatabaseUnavailableError` when the database fails, so `null` always
 * means "not public or does not exist".
 */

import { cardFactsJoinSql, cardFactsSelectSql, type CardFacts } from '../cardFacts';
import type { PublicVersionChangelogRow, Severity } from '../changelog/types';
import { mapChangelogRow, type ChangelogQueryRow } from './changelogRows';
import { LIVE_OWNER_GATES, PUBLIC_VERSION_ROW_GATES } from './gates';
import { dbQuery } from './query';

/**
 * Most versions a list on a page carries (the project timeline, the version sidebar, the compare
 * selectors). A project with more shows its newest ones; the changelog page pages through all.
 */
export const VERSION_LIST_LIMIT = 200;

/** The project page's header row: the project, its organization and its latest version's facts. */
export interface PublicProjectRow extends Partial<CardFacts> {
  id: string;
  name: string;
  slug: string;
  description?: string;
  created_at?: string;
  tenant_name?: string;
  tenant_slug?: string;
  tenant_description?: string;
  /** Published public versions of the project (all of them, not only the ones listed). */
  version_count: number;
}

/** One row of the project page's version timeline. */
export interface ProjectVersionRow {
  id: string;
  version_id: string;
  description?: string;
  change_log?: string;
  published: boolean;
  published_at?: string;
  created_at?: string;
  /** The version's classified severity, when its changelog has been classified. */
  max_severity: Severity | null;
}

/** A version as a selector or a sidebar lists it. */
export interface VersionLabelRow {
  id: string;
  version_id: string;
}

/** Everything the version page renders, from one statement. */
export interface PublicVersionPage {
  /** The version with its project, organization and card facts. */
  version: Record<string, unknown> & { id: string; version_id: string; mock_enabled?: boolean };
  /** The project's public versions, newest first, for the sidebar (at most {@link VERSION_LIST_LIMIT}). */
  versions: VersionLabelRow[];
  /** The stored changelog; its entries are present only when asked for. */
  changelog: PublicVersionChangelogRow;
}

/**
 * A public project with the card facts of its latest published public version.
 *
 * @param tenantSlug - The organization's slug.
 * @param projectSlug - The project's slug.
 * @returns The project, or null when it does not exist or has no public version.
 * @throws DatabaseUnavailableError When the database fails.
 */
export async function getPublicProjectWithFacts(
  tenantSlug: string,
  projectSlug: string
): Promise<PublicProjectRow | null> {
  const result = await dbQuery<PublicProjectRow>(
    'getPublicProjectWithFacts',
    `SELECT p.id, p.name, p.slug, p.description, p.created_at,
            t.name AS tenant_name, t.slug AS tenant_slug, t.description AS tenant_description,
            b.version_count,
            ${cardFactsSelectSql('cf')}
       FROM apiome.tenants t
       JOIN apiome.projects p ON p.tenant_id = t.id
       JOIN apiome.browse_public_projects b ON b.project_id = p.id
       ${cardFactsJoinSql('b.latest_version_id', 'cf')}
      WHERE t.slug = $1
        AND p.slug = $2
        AND ${LIVE_OWNER_GATES}`,
    [tenantSlug, projectSlug]
  );
  return result.rows[0] ?? null;
}

/**
 * The newest public versions of a project, each with its classified severity.
 *
 * @param projectId - The project's id (from {@link getPublicProjectWithFacts}).
 * @param limit - Most versions to return.
 * @returns The versions, newest first.
 * @throws DatabaseUnavailableError When the database fails.
 */
export async function listProjectVersions(
  projectId: string,
  limit: number = VERSION_LIST_LIMIT
): Promise<ProjectVersionRow[]> {
  const result = await dbQuery<ProjectVersionRow>(
    'listProjectVersions',
    `SELECT v.id, v.version_id, v.description, v.change_log, v.published, v.published_at,
            v.created_at, vc.max_severity
       FROM apiome.versions v
       LEFT JOIN apiome.version_changelogs vc ON vc.published_revision_id = v.id
      WHERE v.project_id = $1
        AND ${PUBLIC_VERSION_ROW_GATES}
      ORDER BY v.created_at DESC
      LIMIT $2`,
    [projectId, limit]
  );
  return result.rows;
}

/**
 * The labels of a project's newest public versions, for the compare selectors.
 *
 * @param projectId - The project's id.
 * @param limit - Most versions to return.
 * @returns `{ id, version_id }` rows, newest first.
 * @throws DatabaseUnavailableError When the database fails.
 */
export async function listVersionLabels(
  projectId: string,
  limit: number = VERSION_LIST_LIMIT
): Promise<VersionLabelRow[]> {
  const result = await dbQuery<VersionLabelRow>(
    'listVersionLabels',
    `SELECT v.id, v.version_id
       FROM apiome.versions v
      WHERE v.project_id = $1
        AND ${PUBLIC_VERSION_ROW_GATES}
      ORDER BY v.created_at DESC
      LIMIT $2`,
    [projectId, limit]
  );
  return result.rows;
}

/** The columns of the version page's row that belong to the sidebar list or to the changelog. */
const VERSION_PAGE_EXTRA_COLUMNS = [
  'sidebar_versions',
  'published_revision_id',
  'version_label',
  'baseline_version_label',
  'max_severity',
  'status',
  'changelog_json',
] as const;

/** The version page's row, before it is split into its three parts. */
type VersionPageRow = ChangelogQueryRow & {
  id: string;
  version_id: string;
  sidebar_versions: VersionLabelRow[] | null;
  [column: string]: unknown;
};

/**
 * The version page, in one statement.
 *
 * @param tenantSlug - The organization's slug.
 * @param projectSlug - The project's slug.
 * @param versionSlug - The version's label.
 * @param withChangelogEntries - Whether to return the changelog's entries (the page opens on the
 *   Changes tab). Without them the changelog row is marked `entriesOmitted`.
 * @returns The page's data, or null when the version is not public or does not exist.
 * @throws DatabaseUnavailableError When the database fails.
 */
export async function getPublicVersionPage(
  tenantSlug: string,
  projectSlug: string,
  versionSlug: string,
  withChangelogEntries: boolean
): Promise<PublicVersionPage | null> {
  const result = await dbQuery<VersionPageRow>(
    'getPublicVersionPage',
    `SELECT v.id, v.version_id, v.description, v.change_log, v.published, v.visibility,
            v.created_at, v.updated_at, v.published_at, v.mock_enabled,
            p.name AS project_name, p.slug AS project_slug, p.description AS project_description,
            t.name AS tenant_name, t.slug AS tenant_slug, t.description AS tenant_description,
            ${cardFactsSelectSql('cf')},
            v.id AS published_revision_id, v.version_id AS version_label,
            bl.version_id AS baseline_version_label,
            vc.max_severity, vc.status,
            CASE WHEN $4::boolean THEN vc.changelog_json
                 ELSE vc.changelog_json - 'entries' END AS changelog_json,
            (SELECT COALESCE(json_agg(json_build_object('id', s.id, 'version_id', s.version_id)
                                      ORDER BY s.created_at DESC), '[]'::json)
               FROM (SELECT sv.id, sv.version_id, sv.created_at
                       FROM apiome.versions sv
                      WHERE sv.project_id = p.id
                        AND sv.published = true
                        AND sv.visibility = 'public'
                        AND sv.deleted_at IS NULL
                      ORDER BY sv.created_at DESC
                      LIMIT ${VERSION_LIST_LIMIT}) s) AS sidebar_versions
       FROM apiome.versions v
       JOIN apiome.projects p ON v.project_id = p.id
       JOIN apiome.tenants t ON p.tenant_id = t.id
       ${cardFactsJoinSql('v.id', 'cf')}
       LEFT JOIN apiome.version_changelogs vc ON vc.published_revision_id = v.id
       LEFT JOIN apiome.versions bl ON bl.id = vc.baseline_revision_id
      WHERE t.slug = $1
        AND p.slug = $2
        AND v.version_id = $3
        AND ${PUBLIC_VERSION_ROW_GATES}
        AND ${LIVE_OWNER_GATES}`,
    [tenantSlug, projectSlug, versionSlug, withChangelogEntries]
  );
  const row = result.rows[0];
  if (!row) return null;
  // The row carries three things; the sidebar list and the changelog columns are not the version.
  const version: Record<string, unknown> = { ...row };
  for (const column of VERSION_PAGE_EXTRA_COLUMNS) delete version[column];
  return {
    version: version as PublicVersionPage['version'],
    versions: row.sidebar_versions ?? [],
    changelog: mapChangelogRow(row, !withChangelogEntries),
  };
}
