'use server';

import { unstable_noStore as noStore } from 'next/cache';
import connectionPool from './db';
import { cachedRead } from './ttlCache';
import { mcpSortOrderSql, type McpSortMode } from '../mcpSort';
import {
  cardFactsJoinSql,
  cardFactsSelectSql,
  latestPublicVersionJoinSql,
  projectRailOrderSql,
  type ProjectRailSort,
} from '../cardFacts';
import {
  OFFICIAL_REGISTRY_URL,
  federateRegistryEntries,
  fetchRegistryServers,
  normalizeRegistryBase,
  registryQuery,
  registryRemoteHosts,
  toClientEntry,
  type McpFederatedRegistryResult,
  type McpPublishedEndpointRef,
} from '../mcp/registrySearch';
import type {
  McpPublicEndpoint,
  McpPublicHostGroup,
  McpPublicCollection,
  McpPublicCatalogBucket,
  McpPublicCatalogInsight,
  McpCapabilityItem,
  McpPublicEndpointDetail,
  McpPublicSearchHit,
} from '../types';
import type {
  ChangelogPayload,
  ChangelogStatus,
  PublicVersionChangelogRow,
  Severity,
} from '../changelog/types';

interface PgError {
  message?: string;
  code?: string;
}

function logError(scope: string, err: unknown) {
  const e = err as PgError;
  console.error(`[db] ${scope}:`, e?.message ?? err);
}

/**
 * Run a statement as a *named* (server-side prepared) statement.
 *
 * The home page's card queries (BDX-2.2) carry the facts join, whose planning costs more than
 * running it on a small catalog. A named statement is planned once per pooled connection and
 * re-used, which keeps the home page's render inside its budget. This is a plan cache, not a data
 * cache: every call still reads current rows, and Postgres re-plans by itself after a migration.
 *
 * @param name - A name unique to this exact `text` (node-postgres rejects one name with two texts
 *   on the same connection, so a variant of the SQL needs its own name).
 * @param text - The statement.
 * @param values - Its parameters.
 * @returns The query result.
 */
function queryPrepared(name: string, text: string, values: unknown[]) {
  return connectionPool.query({ name, text, values });
}

/**
 * Protocol / source-format roll-up for the browse facets (MFI-6.1).
 *
 * Both columns live on `apiome.versions` (MFI-7.1) and are recorded by the import adapters, so an
 * entry's facet values are the distinct values across the published public versions it owns. They
 * are lower-cased and blank-folded here so a chip, a stored row, and a filter all compare in one
 * form — the same normalization `app/browse_facets.py` applies on the API side. Versions imported
 * before the columns existed carry NULL and simply contribute no chip.
 */
const FACET_ROLLUP_SQL = `COALESCE(
           array_agg(DISTINCT NULLIF(LOWER(TRIM(COALESCE(v.protocol, ''))), ''))
             FILTER (WHERE NULLIF(TRIM(COALESCE(v.protocol, '')), '') IS NOT NULL),
           ARRAY[]::text[]
         ) AS protocols,
         COALESCE(
           array_agg(DISTINCT NULLIF(LOWER(TRIM(COALESCE(v.source_format, ''))), ''))
             FILTER (WHERE NULLIF(TRIM(COALESCE(v.source_format, '')), '') IS NOT NULL),
           ARRAY[]::text[]
         ) AS formats`;

/**
 * Get all tenants that have at least one published public version.
 *
 * Each row also carries the distinct protocols/formats the organization publishes, so the
 * directory can be filtered by facet without a second round trip.
 *
 * The list is the same for every visitor, so it is read through the directory cache
 * (`lib/db/ttlCache.ts`, DBP-1.16): a publish shows up here within one refresh interval. The
 * versions are rolled up by tenant id before the tenant rows are joined, so the pass over the
 * public catalog groups on one uuid, not on names and descriptions.
 */
export async function getPublicTenants() {
  noStore();
  try {
    return await cachedRead('public-tenants', async () => {
      const result = await connectionPool.query(
        `SELECT t.id, t.name, t.slug, t.description, t.created_at, a.protocols, a.formats
         FROM (
           SELECT p.tenant_id,
                  ${FACET_ROLLUP_SQL}
           FROM apiome.projects p
           JOIN apiome.versions v ON p.id = v.project_id
           WHERE v.published = true
             AND v.visibility = 'public'
             AND p.deleted_at IS NULL
             AND v.deleted_at IS NULL
           GROUP BY p.tenant_id
         ) a
         JOIN apiome.tenants t ON t.id = a.tenant_id
         WHERE t.deleted_at IS NULL
         ORDER BY t.name ASC`
      );
      return result.rows;
    });
  } catch (err) {
    logError('getPublicTenants', err);
    return [];
  }
}

/**
 * Get all projects for a tenant that have at least one published public version.
 *
 * Each row also carries the distinct protocols/formats across its published public versions, which
 * is what the tenant page's protocol/format facets count and filter on (MFI-6.1), and the card facts
 * of its latest published public version — operation and schema counts, grade, mock, SDK, format,
 * published date (BDX-2.2) — computed in the same statement.
 */
export async function getPublicProjectsForTenant(tenantSlug: string) {
  try {
    const result = await connectionPool.query(
      `WITH tenant_projects AS (
         SELECT p.id, p.name, p.slug, p.description, p.created_at,
                ${FACET_ROLLUP_SQL}
         FROM apiome.projects p
         JOIN apiome.tenants t ON p.tenant_id = t.id
         JOIN apiome.versions v ON p.id = v.project_id
         WHERE t.slug = $1
           AND v.published = true
           AND v.visibility = 'public'
           AND t.deleted_at IS NULL
           AND p.deleted_at IS NULL
           AND v.deleted_at IS NULL
         GROUP BY p.id, p.name, p.slug, p.description, p.created_at
       )
       SELECT tp.*, ${cardFactsSelectSql('cf')}
       FROM tenant_projects tp
       ${latestPublicVersionJoinSql('tp.id', 'lv')}
       ${cardFactsJoinSql('lv.id', 'cf')}
       ORDER BY tp.name ASC`,
      [tenantSlug]
    );
    return result.rows;
  } catch (err) {
    logError('getPublicProjectsForTenant', err);
    return [];
  }
}

/**
 * Get all published public versions for a project.
 */
export async function getPublicVersionsForProject(tenantSlug: string, projectSlug: string) {
  try {
    const result = await connectionPool.query(
      `SELECT v.id, v.version_id, v.description, v.change_log, v.published, v.visibility,
              v.created_at, v.updated_at, v.published_at
       FROM apiome.versions v
       JOIN apiome.projects p ON v.project_id = p.id
       JOIN apiome.tenants t ON p.tenant_id = t.id
       WHERE t.slug = $1
         AND p.slug = $2
         AND v.published = true
         AND v.visibility = 'public'
         AND t.deleted_at IS NULL
         AND p.deleted_at IS NULL
         AND v.deleted_at IS NULL
       ORDER BY v.created_at DESC`,
      [tenantSlug, projectSlug]
    );
    return result.rows;
  } catch (err) {
    logError('getPublicVersionsForProject', err);
    return [];
  }
}

/**
 * Get version details by tenant, project, and version slugs, with the version's card facts
 * (BDX-2.2) for the version header.
 */
export async function getPublicVersionDetails(
  tenantSlug: string,
  projectSlug: string,
  versionSlug: string
) {
  try {
    const result = await connectionPool.query(
      `SELECT v.id, v.version_id, v.description, v.change_log, v.published, v.visibility,
              v.created_at, v.updated_at, v.published_at, v.mock_enabled,
              p.name as project_name, p.slug as project_slug, p.description as project_description,
              t.name as tenant_name, t.slug as tenant_slug, t.description as tenant_description,
              ${cardFactsSelectSql('cf')}
       FROM apiome.versions v
       JOIN apiome.projects p ON v.project_id = p.id
       JOIN apiome.tenants t ON p.tenant_id = t.id
       ${cardFactsJoinSql('v.id', 'cf')}
       WHERE t.slug = $1
         AND p.slug = $2
         AND v.version_id = $3
         AND v.published = true
         AND v.visibility = 'public'
         AND t.deleted_at IS NULL
         AND p.deleted_at IS NULL
         AND v.deleted_at IS NULL`,
      [tenantSlug, projectSlug, versionSlug]
    );
    return result.rows.length > 0 ? result.rows[0] : null;
  } catch (err) {
    logError('getPublicVersionDetails', err);
    return null;
  }
}

/**
 * Columns shared by the two changelog reads (CTG-3.2, #4476): the version's identity plus its
 * (optional) classification row and baseline label. The private `error` column is deliberately
 * never selected — a failed row surfaces publicly only as `status = 'failed'`.
 */
const VERSION_CHANGELOG_SELECT = `
       SELECT v.id AS published_revision_id, v.version_id AS version_label, v.published_at,
              bl.version_id AS baseline_version_label,
              vc.max_severity, vc.status, vc.changelog_json
       FROM apiome.versions v
       JOIN apiome.projects p ON v.project_id = p.id
       JOIN apiome.tenants t ON p.tenant_id = t.id
       LEFT JOIN apiome.version_changelogs vc ON vc.published_revision_id = v.id
       LEFT JOIN apiome.versions bl ON bl.id = vc.baseline_revision_id`;

/** Map one snake_case changelog query row to the camelCase public shape. */
function mapChangelogRow(row: {
  published_revision_id: string;
  version_label: string;
  published_at: string | Date | null;
  baseline_version_label: string | null;
  max_severity: string | null;
  status: string | null;
  changelog_json: unknown;
}): PublicVersionChangelogRow {
  return {
    publishedRevisionId: row.published_revision_id,
    versionLabel: row.version_label,
    publishedAt: row.published_at,
    baselineVersionLabel: row.baseline_version_label,
    maxSeverity: (row.max_severity as Severity | null) ?? null,
    status: (row.status as ChangelogStatus | null) ?? null,
    changelog: (row.changelog_json as ChangelogPayload | null) ?? null,
  };
}

/**
 * The stored publish changelog for one published public version (CTG-3.2, #4476).
 *
 * Returns null when the version itself is not publicly visible (same gates as
 * `getPublicVersionDetails`); a visible version with no classification row yet returns a row with
 * null `status`/`changelog` so the caller can render a "pending" state.
 */
export async function getPublicVersionChangelog(
  tenantSlug: string,
  projectSlug: string,
  versionSlug: string
): Promise<PublicVersionChangelogRow | null> {
  noStore();
  try {
    const result = await connectionPool.query(
      `${VERSION_CHANGELOG_SELECT}
       WHERE t.slug = $1
         AND p.slug = $2
         AND v.version_id = $3
         AND v.published = true
         AND v.visibility = 'public'
         AND t.deleted_at IS NULL
         AND p.deleted_at IS NULL
         AND v.deleted_at IS NULL`,
      [tenantSlug, projectSlug, versionSlug]
    );
    return result.rows.length > 0 ? mapChangelogRow(result.rows[0]) : null;
  } catch (err) {
    logError('getPublicVersionChangelog', err);
    return null;
  }
}

/**
 * Stored publish changelogs for every published public version of a project, newest
 * `published_at` first (one row per version via LEFT JOIN, so versions without a classification
 * row still appear as "pending"). Powers the changelog feeds, the project timeline severity
 * pills, and the compare page's severity chips (CTG-3.2, #4476).
 */
export async function getPublicChangelogsForProject(
  tenantSlug: string,
  projectSlug: string,
  limit = 50
): Promise<PublicVersionChangelogRow[]> {
  noStore();
  try {
    const result = await connectionPool.query(
      `${VERSION_CHANGELOG_SELECT}
       WHERE t.slug = $1
         AND p.slug = $2
         AND v.published = true
         AND v.visibility = 'public'
         AND t.deleted_at IS NULL
         AND p.deleted_at IS NULL
         AND v.deleted_at IS NULL
       ORDER BY v.published_at DESC NULLS LAST, v.created_at DESC
       LIMIT $3`,
      [tenantSlug, projectSlug, limit]
    );
    return result.rows.map(mapChangelogRow);
  } catch (err) {
    logError('getPublicChangelogsForProject', err);
    return [];
  }
}

/**
 * Get the declared OpenAPI `servers[]` rows for a published public version (SIM-3.2, #4448).
 *
 * Powers the Try It relay's server-side host allow-policy: only origins declared by the
 * version's own spec may be targeted with `target.kind === 'spec'`. Returns an empty list when
 * the version is unknown, not public, or the query fails — the relay then refuses (fail closed).
 */
export async function getPublicVersionServers(
  tenantSlug: string,
  projectSlug: string,
  versionSlug: string
): Promise<{ url: string; variables: unknown }[]> {
  try {
    const result = await connectionPool.query(
      `SELECT vs.url, vs.variables
       FROM apiome.version_server vs
       JOIN apiome.versions v ON vs.version_id = v.id
       JOIN apiome.projects p ON v.project_id = p.id
       JOIN apiome.tenants t ON p.tenant_id = t.id
       WHERE t.slug = $1
         AND p.slug = $2
         AND v.version_id = $3
         AND v.published = true
         AND v.visibility = 'public'
         AND t.deleted_at IS NULL
         AND p.deleted_at IS NULL
         AND v.deleted_at IS NULL
       ORDER BY vs.sort_order, vs.url`,
      [tenantSlug, projectSlug, versionSlug]
    );
    return result.rows as { url: string; variables: unknown }[];
  } catch (err) {
    logError('getPublicVersionServers', err);
    return [];
  }
}

// Catalog search moved to lib/search/sql.ts + lib/db/search.ts (browse retail search).

/**
 * Get tenant details by slug.
 */
export async function getPublicTenantBySlug(tenantSlug: string) {
  try {
    const result = await connectionPool.query(
      `SELECT DISTINCT t.id, t.name, t.slug, t.description, t.created_at
       FROM apiome.tenants t
       JOIN apiome.projects p ON t.id = p.tenant_id
       JOIN apiome.versions v ON p.id = v.project_id
       WHERE t.slug = $1
         AND v.published = true
         AND v.visibility = 'public'
         AND t.deleted_at IS NULL
         AND p.deleted_at IS NULL
         AND v.deleted_at IS NULL`,
      [tenantSlug]
    );
    return result.rows.length > 0 ? result.rows[0] : null;
  } catch (err) {
    logError('getPublicTenantBySlug', err);
    return null;
  }
}

/**
 * Get project details by tenant and project slugs, with the card facts of the project's latest
 * published public version (BDX-2.2) for the project header.
 */
export async function getPublicProjectBySlug(tenantSlug: string, projectSlug: string) {
  try {
    const result = await connectionPool.query(
      `SELECT p.id, p.name, p.slug, p.description, p.created_at,
              t.name as tenant_name, t.slug as tenant_slug, t.description as tenant_description,
              ${cardFactsSelectSql('cf')}
       FROM apiome.projects p
       JOIN apiome.tenants t ON p.tenant_id = t.id
       ${latestPublicVersionJoinSql('p.id', 'lv')}
       ${cardFactsJoinSql('lv.id', 'cf')}
       WHERE t.slug = $1
         AND p.slug = $2
         AND lv.id IS NOT NULL
         AND t.deleted_at IS NULL
         AND p.deleted_at IS NULL
       LIMIT 1`,
      [tenantSlug, projectSlug]
    );
    return result.rows.length > 0 ? result.rows[0] : null;
  } catch (err) {
    logError('getPublicProjectBySlug', err);
    return null;
  }
}

/**
 * Recently published public versions across all tenants/projects, each with its card facts
 * (BDX-2.2). Used by the discovery home page; read through the directory cache (DBP-1.16).
 */
export async function getRecentlyPublishedVersions(limit = 8) {
  noStore();
  try {
    return await cachedRead(`home-recent-versions:${limit}`, async () => {
      const result = await queryPrepared(
        'browse-home-recent-versions-v1',
        // The facts join runs on the limited page only, so the counts cost `limit` lookups.
        `WITH recent AS (
           SELECT v.id, v.version_id, v.description, v.published_at, v.created_at,
                  p.name as project_name, p.slug as project_slug, p.description as project_description,
                  t.name as tenant_name, t.slug as tenant_slug
           FROM apiome.versions v
           JOIN apiome.projects p ON v.project_id = p.id
           JOIN apiome.tenants t ON p.tenant_id = t.id
           WHERE v.published = true
             AND v.visibility = 'public'
             AND t.deleted_at IS NULL
             AND p.deleted_at IS NULL
             AND v.deleted_at IS NULL
           ORDER BY v.published_at DESC NULLS LAST, v.created_at DESC
           LIMIT $1
         )
         SELECT r.id, r.version_id, r.description, r.published_at,
                r.project_name, r.project_slug, r.project_description, r.tenant_name, r.tenant_slug,
                ${cardFactsSelectSql('cf')}
         FROM recent r
         ${cardFactsJoinSql('r.id', 'cf')}
         ORDER BY r.published_at DESC NULLS LAST, r.created_at DESC`,
        [limit]
      );
      return result.rows;
    });
  } catch (err) {
    logError('getRecentlyPublishedVersions', err);
    return [];
  }
}

/**
 * Public projects for the home page's project rail, each with the card facts of its latest
 * published public version (BDX-2.2).
 *
 * `sort` picks the rail: most versions (a proxy for "active" projects, the default), most
 * operations, or best grade.
 *
 * The statement (DBP-1.16) counts public versions per project id first — one narrow aggregate —
 * and only then joins project and tenant rows. In the default order it keeps `limit` projects
 * before it looks at any version's facts. The other two orders have to rank every public project,
 * so they first read the *ranking* columns of each project's latest version (the stored
 * `operation_count`, or the grade) and compute the full facts for the `limit` winners only. Each
 * rail is read through the directory cache.
 *
 * @param limit - How many projects the rail shows.
 * @param sort - The rail order (validated by `parseProjectRailSort`).
 */
export async function getMostVersionedProjects(limit = 8, sort: ProjectRailSort = 'versions') {
  noStore();
  const rankByFacts = sort !== 'versions';
  // The columns `projectRailOrderSql` ranks by, read from the latest version without the facts
  // join. A version whose operation count is not stored ranks by a per-version count.
  const rankColumnsSql = `(SELECT COALESCE(r_v.operation_count,
                     (SELECT COUNT(*)::int
                        FROM apiome.version_path r_vp
                        JOIN apiome.path_operation r_po ON r_po.version_path_id = r_vp.id
                       WHERE r_vp.version_id = r_v.id)) AS operation_count,
                   NULLIF(TRIM(r_v.quality_grade), '') AS quality_grade,
                   r_v.quality_score::int AS quality_score
              FROM apiome.versions r_v WHERE r_v.id = lv.id)`;
  try {
    return await cachedRead(`home-project-rail:${sort}:${limit}`, async () => {
      const result = await queryPrepared(
        `browse-home-project-rail-${sort}-v2`,
        `WITH counted AS (
           SELECT v.project_id,
                  COUNT(*)::int as version_count,
                  MAX(v.published_at) as latest_published_at
           FROM apiome.versions v
           WHERE v.published = true
             AND v.visibility = 'public'
             AND v.deleted_at IS NULL
           GROUP BY v.project_id
         ),
         project_versions AS (
           SELECT p.id, p.name, p.slug, p.description,
                  t.name as tenant_name, t.slug as tenant_slug,
                  c.version_count, c.latest_published_at
           FROM counted c
           JOIN apiome.projects p ON p.id = c.project_id
           JOIN apiome.tenants t ON p.tenant_id = t.id
           WHERE t.deleted_at IS NULL
             AND p.deleted_at IS NULL
           ${rankByFacts ? '' : `ORDER BY ${projectRailOrderSql('versions')}
           LIMIT $1`}
         ),
         ranked AS (
           SELECT pv.*, lv.id AS latest_version_pk
           FROM project_versions pv
           ${latestPublicVersionJoinSql('pv.id', 'lv')}
           ${rankByFacts ? `LEFT JOIN LATERAL ${rankColumnsSql} cf ON TRUE
           ORDER BY ${projectRailOrderSql(sort)}
           LIMIT $1` : ''}
         )
         SELECT rk.id, rk.name, rk.slug, rk.description, rk.tenant_name, rk.tenant_slug,
                rk.version_count, rk.latest_published_at,
                ${cardFactsSelectSql('cf')}
         FROM ranked rk
         ${cardFactsJoinSql('rk.latest_version_pk', 'cf')}
         ORDER BY ${projectRailOrderSql(sort)}`,
        [limit]
      );
      return result.rows;
    });
  } catch (err) {
    logError('getMostVersionedProjects', err);
    return [];
  }
}

/**
 * Newest public organizations (those with at least one published public version).
 *
 * Walks tenants newest first and stops at `limit`, probing each for one public version (`EXISTS`),
 * instead of joining every public version to find the distinct tenants (DBP-1.16). Read through
 * the directory cache.
 */
export async function getNewestTenants(limit = 8) {
  noStore();
  try {
    return await cachedRead(`home-newest-tenants:${limit}`, async () => {
      const result = await connectionPool.query(
        `SELECT t.id, t.name, t.slug, t.description, t.created_at
         FROM apiome.tenants t
         WHERE t.deleted_at IS NULL
           AND EXISTS (
             SELECT 1
             FROM apiome.projects p
             JOIN apiome.versions v ON p.id = v.project_id
             WHERE p.tenant_id = t.id
               AND p.deleted_at IS NULL
               AND v.published = true
               AND v.visibility = 'public'
               AND v.deleted_at IS NULL
           )
         ORDER BY t.created_at DESC
         LIMIT $1`,
        [limit]
      );
      return result.rows;
    });
  } catch (err) {
    logError('getNewestTenants', err);
    return [];
  }
}

/** The directory counters, as the navbar and the home hero strip read them. */
interface DirectoryStatsRow {
  tenant_count: number;
  project_count: number;
  version_count: number;
}

/**
 * Aggregate counts for the navbar and the home hero strip: organizations, projects and versions
 * that are published and public.
 *
 * The root layout awaits this on every page, so it is read through the directory cache
 * (DBP-1.16): one count per refresh interval and Browse process, not one per page view. The counts
 * can therefore trail a publish by up to that interval (`BROWSE_CACHE_TTL_SECONDS`, 120 s by
 * default). When a refresh fails the previous counts stay up; with none to show, zeros.
 */
export async function getDirectoryStats(): Promise<DirectoryStatsRow> {
  noStore();
  try {
    return await cachedRead<DirectoryStatsRow>('directory-stats', async () => {
      const result = await connectionPool.query<DirectoryStatsRow>(
        // One row per public version, so COUNT(*) is the version count.
        `SELECT
           COUNT(DISTINCT p.tenant_id)::int as tenant_count,
           COUNT(DISTINCT p.id)::int as project_count,
           COUNT(*)::int as version_count
         FROM apiome.versions v
         JOIN apiome.projects p ON p.id = v.project_id
         JOIN apiome.tenants t ON t.id = p.tenant_id
         WHERE v.published = true
           AND v.visibility = 'public'
           AND t.deleted_at IS NULL
           AND p.deleted_at IS NULL
           AND v.deleted_at IS NULL`
      );
      return result.rows[0] ?? { tenant_count: 0, project_count: 0, version_count: 0 };
    });
  } catch (err) {
    logError('getDirectoryStats', err);
    return { tenant_count: 0, project_count: 0, version_count: 0 };
  }
}

// ---------------------------------------------------------------------------------------------------
// Public MCP catalog (V2-MCP-23.6 / 23.7 — MCAT-9.6 / 9.7)
//
// All MCP browse/search reads go through the `apiome.mcp_v_public_endpoints` view (V134), which already
// filters to enabled + published + public-visible endpoints and never exposes the raw endpoint_url.
// Because these helpers only ever touch that view, private endpoints can never surface here.
// ---------------------------------------------------------------------------------------------------

/**
 * The exact tsvector expression the V127 GIN index (`idx_mcp_capability_items_fts`) is built on, so
 * the index backs the public capability search rather than a sequential scan.
 */
const MCP_CAPABILITY_FTS =
  "to_tsvector('english', coalesce(ci.name, '') || ' ' || coalesce(ci.description, ''))";

/** Per-snapshot capability counts, shared by the browse list and grouping query. */
const MCP_CAPABILITY_COUNTS = `
  COUNT(ci.id) FILTER (WHERE ci.item_type = 'tool')::int AS tool_count,
  COUNT(ci.id) FILTER (WHERE ci.item_type = 'resource')::int AS resource_count,
  COUNT(ci.id) FILTER (WHERE ci.item_type = 'resource_template')::int AS resource_template_count,
  COUNT(ci.id) FILTER (WHERE ci.item_type = 'prompt')::int AS prompt_count`;

/**
 * Every published public MCP endpoint, grouped by host (alphabetically) and grade-led within each
 * host group (grade ascending A→F, ungraded last, then score, then name). Each endpoint carries its
 * current snapshot's capability counts. Powers the idle public browse index (MCAT-9.6).
 */
export async function getPublicMcpEndpointsByHost(): Promise<McpPublicHostGroup[]> {
  noStore();
  try {
    const result = await connectionPool.query(
      `SELECT e.id, e.tenant_id, t.slug AS tenant_slug, e.name, e.slug, e.category, e.transport,
              e.description, e.current_version_id, e.host, e.score, e.grade, e.scored_at,
              e.last_discovered_at, e.updated_at,
              ${MCP_CAPABILITY_COUNTS}
       FROM apiome.mcp_v_public_endpoints e
       JOIN apiome.tenants t ON t.id = e.tenant_id AND t.deleted_at IS NULL
       LEFT JOIN apiome.mcp_capability_items ci ON ci.version_id = e.current_version_id
       GROUP BY e.id, e.tenant_id, t.slug, e.name, e.slug, e.category, e.transport, e.description,
                e.current_version_id, e.host, e.score, e.grade, e.scored_at,
                e.last_discovered_at, e.updated_at
       ORDER BY e.host ASC NULLS LAST, ${mcpSortOrderSql('top_graded')}`
    );

    const groups: McpPublicHostGroup[] = [];
    let current: McpPublicHostGroup | null = null;
    for (const row of result.rows as McpPublicEndpoint[]) {
      const host = row.host ?? 'Unknown host';
      if (!current || current.host !== host) {
        current = { host, endpoints: [] };
        groups.push(current);
      }
      current.endpoints.push(row);
    }
    return groups;
  } catch (err) {
    logError('getPublicMcpEndpointsByHost', err);
    return [];
  }
}

/**
 * The public catalog analytics roll-up (V2-MCP-32.1 / MCAT-18.1) — a reduced, credential-free variant
 * of the private dashboard. Aggregates only over `apiome.mcp_v_public_endpoints`, so it inherently
 * respects published-only + public visibility (the acceptance criterion) and can only ever expose the
 * view's own columns: the endpoint count, the average score, and the category / transport / grade
 * mixes. NULL categories fold into "Uncategorized"; each mix is ordered busiest-first with a stable
 * label tiebreak. An empty catalog returns zeroes and empty mixes (never throws); any query failure
 * logs and returns the same safe empty shape so the page renders its empty state, not a 500.
 */
export async function getPublicCatalogInsight(): Promise<McpPublicCatalogInsight> {
  noStore();
  const empty: McpPublicCatalogInsight = {
    endpoint_count: 0,
    average_score: null,
    category_distribution: [],
    transport_distribution: [],
    grade_distribution: [],
  };
  try {
    // A single round trip: the scalar summary and the three mixes as JSON aggregates, all scoped to
    // the public view so private / unpublished endpoints can never move a tile.
    const result = await connectionPool.query(
      `WITH pub AS (
         SELECT category, transport, grade, score FROM apiome.mcp_v_public_endpoints
       ),
       cats AS (
         SELECT COALESCE(category, 'Uncategorized') AS label, COUNT(*)::int AS count
         FROM pub GROUP BY COALESCE(category, 'Uncategorized')
         ORDER BY count DESC, label ASC
       ),
       transports AS (
         SELECT transport AS label, COUNT(*)::int AS count
         FROM pub GROUP BY transport
         ORDER BY count DESC, label ASC
       ),
       grades AS (
         SELECT grade AS label, COUNT(*)::int AS count
         FROM pub WHERE grade IS NOT NULL GROUP BY grade
         ORDER BY grade ASC
       )
       SELECT
         (SELECT COUNT(*)::int FROM pub) AS endpoint_count,
         (SELECT AVG(score) FROM pub) AS average_score,
         COALESCE((SELECT json_agg(json_build_object('label', label, 'count', count)) FROM cats), '[]') AS category_distribution,
         COALESCE((SELECT json_agg(json_build_object('label', label, 'count', count)) FROM transports), '[]') AS transport_distribution,
         COALESCE((SELECT json_agg(json_build_object('label', label, 'count', count)) FROM grades), '[]') AS grade_distribution`
    );
    const row = result.rows[0];
    if (!row) return empty;
    const avg = row.average_score;
    return {
      endpoint_count: Number(row.endpoint_count) || 0,
      average_score: avg === null || avg === undefined ? null : Math.round(Number(avg) * 10) / 10,
      category_distribution: (row.category_distribution as McpPublicCatalogBucket[]) ?? [],
      transport_distribution: (row.transport_distribution as McpPublicCatalogBucket[]) ?? [],
      grade_distribution: (row.grade_distribution as McpPublicCatalogBucket[]) ?? [],
    };
  } catch (err) {
    logError('getPublicCatalogInsight', err);
    return empty;
  }
}

/**
 * A single published public endpoint addressed by tenant + endpoint slug, with its current
 * snapshot's capability items (tools/resources/resource templates/prompts) in declared order.
 * Returns null when no such public endpoint exists (→ notFound). Powers endpoint detail (MCAT-9.6).
 */
export async function getPublicMcpEndpointDetail(
  tenantSlug: string,
  endpointSlug: string
): Promise<McpPublicEndpointDetail | null> {
  noStore();
  try {
    const endpointResult = await connectionPool.query(
      `SELECT e.id, e.tenant_id, t.slug AS tenant_slug, e.name, e.slug, e.category, e.transport,
              e.description, e.current_version_id, e.host, e.score, e.grade, e.scored_at,
              e.last_discovered_at, e.updated_at,
              ${MCP_CAPABILITY_COUNTS}
       FROM apiome.mcp_v_public_endpoints e
       JOIN apiome.tenants t ON t.id = e.tenant_id
       LEFT JOIN apiome.mcp_capability_items ci ON ci.version_id = e.current_version_id
       WHERE t.slug = $1 AND e.slug = $2 AND t.deleted_at IS NULL
       GROUP BY e.id, e.tenant_id, t.slug, e.name, e.slug, e.category, e.transport, e.description,
                e.current_version_id, e.host, e.score, e.grade, e.scored_at,
                e.last_discovered_at, e.updated_at`,
      [tenantSlug, endpointSlug]
    );
    if (endpointResult.rows.length === 0) return null;
    const endpoint = endpointResult.rows[0] as McpPublicEndpoint;

    const itemsResult = endpoint.current_version_id
      ? await connectionPool.query(
          `SELECT ci.id, ci.item_type, ci.name, ci.title, ci.description,
                  ci.uri, ci.uri_template, ci.ordinal
           FROM apiome.mcp_capability_items ci
           WHERE ci.version_id = $1
           ORDER BY ci.item_type ASC, ci.ordinal ASC, ci.name ASC`,
          [endpoint.current_version_id]
        )
      : { rows: [] as McpCapabilityItem[] };

    return { endpoint, items: itemsResult.rows as McpCapabilityItem[] };
  } catch (err) {
    logError('getPublicMcpEndpointDetail', err);
    return null;
  }
}

/**
 * One published curated collection for a tenant, listing only endpoints that pass the public
 * visibility gate (`mcp_v_public_endpoints`). Private or unpublished endpoints in the collection are
 * omitted rather than leaking into anonymous browse (MCAT-22.4).
 */
export async function getPublicMcpCollection(
  tenantSlug: string,
  collectionSlug: string
): Promise<McpPublicCollection | null> {
  noStore();
  try {
    const collectionResult = await connectionPool.query(
      `SELECT c.id, c.tenant_id, t.slug AS tenant_slug, t.name AS tenant_name,
              c.name, c.slug, c.description
       FROM apiome.mcp_collections c
       JOIN apiome.tenants t ON t.id = c.tenant_id AND t.deleted_at IS NULL
       WHERE t.slug = $1 AND c.slug = $2 AND c.is_published IS TRUE
       LIMIT 1`,
      [tenantSlug, collectionSlug]
    );
    if (collectionResult.rows.length === 0) return null;
    const collection = collectionResult.rows[0] as {
      id: string;
      tenant_id: string;
      tenant_slug: string;
      tenant_name: string;
      name: string;
      slug: string;
      description: string | null;
    };

    const endpointsResult = await connectionPool.query(
      `SELECT e.id, e.tenant_id, t.slug AS tenant_slug, e.name, e.slug, e.category, e.transport,
              e.description, e.current_version_id, e.host, e.score, e.grade, e.scored_at,
              e.last_discovered_at, e.updated_at,
              ${MCP_CAPABILITY_COUNTS}
       FROM apiome.mcp_collection_members m
       JOIN apiome.mcp_collections c ON c.id = m.collection_id
       JOIN apiome.tenants t ON t.id = c.tenant_id AND t.deleted_at IS NULL
       JOIN apiome.mcp_v_public_endpoints e ON e.id = m.endpoint_id AND e.tenant_id = m.tenant_id
       LEFT JOIN apiome.mcp_capability_items ci ON ci.version_id = e.current_version_id
       WHERE c.id = $1::uuid
       GROUP BY e.id, e.tenant_id, t.slug, e.name, e.slug, e.category, e.transport, e.description,
                e.current_version_id, e.host, e.score, e.grade, e.scored_at,
                e.last_discovered_at, e.updated_at, m.position, m.added_at
       ORDER BY m.position ASC, m.added_at ASC, e.name ASC`,
      [collection.id]
    );

    return {
      ...collection,
      endpoints: endpointsResult.rows as McpPublicEndpoint[],
    };
  } catch (err) {
    logError('getPublicMcpCollection', err);
    return null;
  }
}

/**
 * Full-text capability search over the public MCP catalog. Reuses the V127 tsvector GIN index
 * (via {@link MCP_CAPABILITY_FTS}) and `websearch_to_tsquery`, which tolerates messy user input.
 *
 * Ordering (MCAT-9.7): relevance-first while a query is present, grade-led when idle, with the
 * caller able to override the mode. The mode is resolved/validated upstream and passed in; an empty
 * query short-circuits to no results (the browse index handles idle browsing).
 */
export async function searchPublicMcpCatalog(
  query: string,
  sortMode: McpSortMode
): Promise<McpPublicSearchHit[]> {
  noStore();
  const q = query.trim();
  if (!q) return [];
  try {
    const result = await connectionPool.query(
      `SELECT e.id AS endpoint_id, e.tenant_id, t.slug AS tenant_slug,
              e.name AS endpoint_name, e.slug AS endpoint_slug,
              e.host, e.category, e.transport, e.score, e.grade,
              ci.item_type, ci.id AS item_id, ci.name AS item_name, ci.title AS item_title,
              ci.description,
              ts_rank(${MCP_CAPABILITY_FTS}, websearch_to_tsquery('english', $1)) AS relevance
       FROM apiome.mcp_v_public_endpoints e
       JOIN apiome.tenants t ON t.id = e.tenant_id AND t.deleted_at IS NULL
       JOIN apiome.mcp_capability_items ci ON ci.version_id = e.current_version_id
       WHERE ${MCP_CAPABILITY_FTS} @@ websearch_to_tsquery('english', $1)
       ORDER BY ${mcpSortOrderSql(sortMode, 'endpoint_name')}, ci.ordinal ASC
       LIMIT 200`,
      [q]
    );
    return result.rows as McpPublicSearchHit[];
  } catch (err) {
    logError('searchPublicMcpCatalog', err);
    return [];
  }
}

/**
 * Published public endpoints a registry entry may duplicate (V2-MCP-26.4, #3710).
 *
 * Reads, in one query, the published endpoints whose registry server name is one of `serverNames`
 * (case-insensitive), whose URL host is one of `hosts`, or whose id is one of `endpointIds` (the
 * catalog hits, so a registry import is labeled even when the search did not return its entry).
 * Only `mcp_v_public_endpoints` rows qualify; the raw `endpoint_url` is joined from
 * `mcp_endpoints` for the server-side URL comparison and never leaves this process.
 *
 * @param serverNames - Registry server names the search returned.
 * @param hosts - Lower-case hosts of those entries' remotes.
 * @param endpointIds - Endpoint ids of the catalog hits.
 * @returns Matching rows; `[]` when every list is empty or the query fails.
 */
async function findPublishedMcpEndpointsForRegistryDedupe(
  serverNames: string[],
  hosts: string[],
  endpointIds: string[]
): Promise<McpPublishedEndpointRef[]> {
  if (!serverNames.length && !hosts.length && !endpointIds.length) return [];
  try {
    const result = await connectionPool.query(
      `SELECT v.id AS endpoint_id, e.endpoint_url,
              CASE WHEN e.added_via = 'registry' THEN e.registry_metadata->>'serverName' END
                AS registry_server_name
       FROM apiome.mcp_v_public_endpoints v
       JOIN apiome.mcp_endpoints e ON e.id = v.id
       WHERE lower(e.registry_metadata->>'serverName') = ANY($1::text[])
          OR lower(v.host) = ANY($2::text[])
          OR v.id = ANY($3::uuid[])`,
      [serverNames.map((n) => n.toLowerCase()), hosts, endpointIds]
    );
    return result.rows as McpPublishedEndpointRef[];
  } catch (err) {
    logError('findPublishedMcpEndpointsForRegistryDedupe', err);
    return [];
  }
}

/**
 * The MCP registry half of a federated public search (V2-MCP-26.4, #3710).
 *
 * Asks the registry (`MCP_REGISTRY_SEARCH_URL`, the official registry by default; blank turns
 * federation off) for servers whose names match `query`, then drops the entries a published
 * endpoint already is ({@link federateRegistryEntries}). A registry that is slow, down or refuses
 * yields `error` and no entries — the catalog results render either way.
 *
 * @param query - The sanitized search query.
 * @param catalogEndpointIds - Endpoint ids of the catalog hits (to label registry imports).
 * @returns The deduped, browser-safe registry result.
 */
export async function searchRegistryForPublicCatalog(
  query: string,
  catalogEndpointIds: string[]
): Promise<McpFederatedRegistryResult> {
  noStore();
  const configured = process.env.MCP_REGISTRY_SEARCH_URL;
  const registryUrl = normalizeRegistryBase(configured === undefined ? OFFICIAL_REGISTRY_URL : configured);
  const empty = { entries: [], duplicates: 0, serverNameByEndpoint: {} };
  if (!registryUrl) {
    return { ...empty, included: false, registryUrl: null, error: 'MCP Registry search is turned off on this site.' };
  }
  let entries;
  try {
    entries = await fetchRegistryServers(registryQuery(query), { baseUrl: registryUrl });
  } catch (err) {
    logError('searchRegistryForPublicCatalog', err);
    return { ...empty, included: false, registryUrl, error: 'The MCP Registry could not be reached.' };
  }
  const published = await findPublishedMcpEndpointsForRegistryDedupe(
    entries.map((e) => e.serverName),
    registryRemoteHosts(entries),
    [...new Set(catalogEndpointIds)]
  );
  const result = federateRegistryEntries(entries, published);
  return {
    included: true,
    registryUrl,
    entries: result.entries.map(toClientEntry),
    duplicates: result.duplicates,
    serverNameByEndpoint: result.serverNameByEndpoint,
    error: null,
  };
}
