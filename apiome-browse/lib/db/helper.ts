'use server';

import { unstable_noStore as noStore } from 'next/cache';
import { cachedRead } from './ttlCache';
import { dbQuery } from './query';
import { LIVE_OWNER_GATES } from './gates';
import { MCP_INDEX_PAGE_SIZE, mcpSortOrderSql, type McpSortMode } from '../mcpSort';
import {
  cardFactsJoinSql,
  cardFactsSelectSql,
  projectRailOrderSql,
  summaryRailOrderSql,
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
  McpPublicIndexPage,
  McpPublicCollection,
  McpPublicCatalogBucket,
  McpPublicCatalogInsight,
  McpCapabilityItem,
  McpPublicEndpointDetail,
  McpPublicSearchHit,
} from '../types';

/**
 * The public directory's reads: the home page, the organization page and the MCP catalog.
 *
 * Since DBP-1.27 (#7210) the catalog-wide reads — organizations, the project rail in each of its
 * orders, newest organizations, the directory counters — read `apiome.browse_public_projects`
 * (V431), one row per public project, instead of passing over every published public version. The
 * reads of single projects and versions live in `lib/db/identity.ts`, `lib/db/versions.ts` and
 * `lib/db/changelogs.ts`.
 *
 * Failure handling (`lib/db/errors.ts`): a read whose empty result a page answers 404 on throws
 * `DatabaseUnavailableError`; the lists that decorate the home page log and return empty.
 */

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
 * @param scope - The reader's name, for the log line.
 * @param name - A name unique to this exact `text` (node-postgres rejects one name with two texts
 *   on the same connection, so a variant of the SQL needs its own name).
 * @param text - The statement.
 * @param values - Its parameters.
 * @returns The query result.
 */
function queryPrepared(scope: string, name: string, text: string, values: unknown[]) {
  return dbQuery(scope, { name, text, values });
}

/**
 * Get all tenants that have at least one published public version.
 *
 * Each row also carries the distinct protocols/formats the organization publishes (MFI-6.1), so
 * the directory can be filtered by facet without a second round trip. They are rolled up from the
 * per-project arrays of the summary table, which already hold them lower-cased and blank-folded —
 * the same normalization `app/browse_facets.py` applies on the API side.
 *
 * The list is the same for every visitor, so it is read through the directory cache
 * (`lib/db/ttlCache.ts`, DBP-1.16): a publish shows up here within one refresh interval.
 */
export async function getPublicTenants() {
  noStore();
  try {
    return await cachedRead('public-tenants', async () => {
      const result = await dbQuery(
        'getPublicTenants',
        `SELECT t.id, t.name, t.slug, t.description, t.created_at, a.protocols, a.formats
         FROM (
           SELECT b.tenant_id,
                  COALESCE(array_agg(DISTINCT pr.value) FILTER (WHERE pr.value IS NOT NULL),
                           ARRAY[]::text[]) AS protocols,
                  COALESCE(array_agg(DISTINCT fm.value) FILTER (WHERE fm.value IS NOT NULL),
                           ARRAY[]::text[]) AS formats
           FROM apiome.browse_public_projects b
           LEFT JOIN LATERAL unnest(b.protocols) AS pr(value) ON TRUE
           LEFT JOIN LATERAL unnest(b.formats) AS fm(value) ON TRUE
           GROUP BY b.tenant_id
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
 * published date (BDX-2.2) — computed in the same statement. The project list, its facets and the
 * latest version's id come from the summary table (DBP-1.27), so no version is searched for.
 *
 * @throws DatabaseUnavailableError When the database fails (the page is an error, not an
 *   organization without projects).
 */
export async function getPublicProjectsForTenant(tenantSlug: string) {
  const result = await dbQuery(
    'getPublicProjectsForTenant',
    `SELECT p.id, p.name, p.slug, p.description, p.created_at, b.protocols, b.formats,
            ${cardFactsSelectSql('cf')}
     FROM apiome.tenants t
     JOIN apiome.browse_public_projects b ON b.tenant_id = t.id
     JOIN apiome.projects p ON p.id = b.project_id
     ${cardFactsJoinSql('b.latest_version_id', 'cf')}
     WHERE t.slug = $1
       AND ${LIVE_OWNER_GATES}
     ORDER BY p.name ASC`,
    [tenantSlug]
  );
  return result.rows;
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
        'getRecentlyPublishedVersions',
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
 * Every order reads its `limit` winners from an index of the summary table (DBP-1.27) — the
 * version count, the latest version's operation count and its grade are stored there — and only
 * then joins project and tenant rows and computes the full facts, for those `limit` projects. The
 * three orders therefore cost the same. Each rail is read through the directory cache.
 *
 * @param limit - How many projects the rail shows.
 * @param sort - The rail order (validated by `parseProjectRailSort`).
 */
export async function getMostVersionedProjects(limit = 8, sort: ProjectRailSort = 'versions') {
  noStore();
  try {
    return await cachedRead(`home-project-rail:${sort}:${limit}`, async () => {
      const result = await queryPrepared(
        'getMostVersionedProjects',
        `browse-home-project-rail-${sort}-v3`,
        `WITH ranked AS (
           SELECT b.project_id, b.latest_version_id, b.version_count, b.latest_published_at
           FROM apiome.browse_public_projects b
           ORDER BY ${summaryRailOrderSql(sort, 'b')}
           LIMIT $1
         )
         SELECT p.id, p.name, p.slug, p.description,
                t.name as tenant_name, t.slug as tenant_slug,
                rk.version_count, rk.latest_published_at,
                ${cardFactsSelectSql('cf')}
         FROM ranked rk
         JOIN apiome.projects p ON p.id = rk.project_id
         JOIN apiome.tenants t ON t.id = p.tenant_id
         ${cardFactsJoinSql('rk.latest_version_id', 'cf')}
         WHERE ${LIVE_OWNER_GATES}
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
 * Walks tenants newest first and stops at `limit`, probing the summary table for one public
 * project each (DBP-1.27). Read through the directory cache.
 */
export async function getNewestTenants(limit = 8) {
  noStore();
  try {
    return await cachedRead(`home-newest-tenants:${limit}`, async () => {
      const result = await dbQuery(
        'getNewestTenants',
        `SELECT t.id, t.name, t.slug, t.description, t.created_at
         FROM apiome.tenants t
         WHERE t.deleted_at IS NULL
           AND EXISTS (SELECT 1 FROM apiome.browse_public_projects b WHERE b.tenant_id = t.id)
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
 * One pass over the summary table (DBP-1.27): a row per public project, each carrying its version
 * count. The root layout awaits this on every page, so it is also read through the directory
 * cache (DBP-1.16): one count per refresh interval and Browse process, not one per page view. The
 * counts can therefore trail a publish by up to that interval (`BROWSE_CACHE_TTL_SECONDS`, 120 s
 * by default). When a refresh fails the previous counts stay up; with none to show, zeros.
 */
export async function getDirectoryStats(): Promise<DirectoryStatsRow> {
  noStore();
  try {
    return await cachedRead<DirectoryStatsRow>('directory-stats', async () => {
      const result = await dbQuery<DirectoryStatsRow>(
        'getDirectoryStats',
        `SELECT
           COUNT(DISTINCT b.tenant_id)::int as tenant_count,
           COUNT(*)::int as project_count,
           COALESCE(SUM(b.version_count), 0)::int as version_count
         FROM apiome.browse_public_projects b`
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
// All MCP browse/search reads go through the `apiome.mcp_v_public_endpoints` view (V134; its host
// column is stored since V431), which already filters to enabled + published + public-visible
// endpoints and never exposes the raw endpoint_url. Because these helpers only ever touch that
// view — or `apiome.mcp_endpoints` under the view's own predicates, {@link mcpPublicEndpointGates}
// — private endpoints can never surface here.
// ---------------------------------------------------------------------------------------------------

/**
 * The exact tsvector expression the V127 GIN index (`idx_mcp_capability_items_fts`) is built on, so
 * the index backs the public capability search rather than a sequential scan.
 */
const MCP_CAPABILITY_FTS =
  "to_tsvector('english', coalesce(ci.name, '') || ' ' || coalesce(ci.description, ''))";

/** The endpoint columns every public MCP card shows, for the view aliased `e` joined to tenant `t`. */
const MCP_ENDPOINT_COLUMNS = `e.id, e.tenant_id, t.slug AS tenant_slug, e.name, e.slug, e.category, e.transport,
              e.description, e.current_version_id, e.host, e.score, e.grade, e.scored_at,
              e.last_discovered_at, e.updated_at`;

/**
 * A `LEFT JOIN LATERAL` with the capability counts of one snapshot: one index-only pass over
 * `idx_mcp_capability_items_version_type (version_id, item_type)` per endpoint shown, instead of
 * joining every capability item of every endpoint and grouping on fifteen columns (DBP-1.27).
 *
 * @param versionExpr - A SQL expression for the snapshot id (a column reference written in code).
 * @param alias - The alias the joined row gets.
 * @returns The join clause; the row has `tool_count`, `resource_count`, `resource_template_count`
 *   and `prompt_count`.
 */
function mcpCapabilityCountsJoinSql(versionExpr: string, alias = 'cc'): string {
  return `LEFT JOIN LATERAL (
         SELECT COUNT(*) FILTER (WHERE ci.item_type = 'tool')::int AS tool_count,
                COUNT(*) FILTER (WHERE ci.item_type = 'resource')::int AS resource_count,
                COUNT(*) FILTER (WHERE ci.item_type = 'resource_template')::int AS resource_template_count,
                COUNT(*) FILTER (WHERE ci.item_type = 'prompt')::int AS prompt_count
           FROM apiome.mcp_capability_items ci
          WHERE ci.version_id = ${versionExpr}
       ) ${alias} ON TRUE`;
}

/** The count columns of {@link mcpCapabilityCountsJoinSql}, for a SELECT list. */
const MCP_CAPABILITY_COUNT_COLUMNS = 'cc.tool_count, cc.resource_count, cc.resource_template_count, cc.prompt_count';

/**
 * One page of the published public MCP endpoints, grouped by host (alphabetically) and grade-led
 * within each host group (grade ascending A→F, ungraded last, then score, then name). Each endpoint
 * carries its current snapshot's capability counts. Powers the idle public browse index (MCAT-9.6).
 *
 * The index is paged (DBP-1.27): {@link MCP_INDEX_PAGE_SIZE} endpoints per page in host order, with
 * the capability counts computed for that page only. A host whose endpoints straddle a page
 * boundary appears on both pages with its endpoints split.
 *
 * @param page - The 1-based page number; anything else means the first page.
 * @returns The page's groups and the catalog's totals.
 * @throws DatabaseUnavailableError When the database fails.
 */
export async function getPublicMcpEndpointsByHost(page = 1): Promise<McpPublicIndexPage> {
  noStore();
  const current = Number.isInteger(page) && page >= 1 ? page : 1;
  const result = await dbQuery<McpPublicEndpoint & { total_endpoints: number; total_hosts: number }>(
    'getPublicMcpEndpointsByHost',
    `WITH pub AS (
       SELECT ${MCP_ENDPOINT_COLUMNS}
       FROM apiome.mcp_v_public_endpoints e
       JOIN apiome.tenants t ON t.id = e.tenant_id AND t.deleted_at IS NULL
     ),
     totals AS (
       SELECT COUNT(*)::int AS total_endpoints,
              COUNT(DISTINCT COALESCE(host, ''))::int AS total_hosts
       FROM pub
     ),
     page AS (
       SELECT pub.*,
              ROW_NUMBER() OVER (ORDER BY host ASC NULLS LAST, ${mcpSortOrderSql('top_graded')}, id) AS ord
       FROM pub
       ORDER BY host ASC NULLS LAST, ${mcpSortOrderSql('top_graded')}, id
       LIMIT $1 OFFSET $2
     )
     SELECT pg.id, pg.tenant_id, pg.tenant_slug, pg.name, pg.slug, pg.category, pg.transport,
            pg.description, pg.current_version_id, pg.host, pg.score, pg.grade, pg.scored_at,
            pg.last_discovered_at, pg.updated_at,
            ${MCP_CAPABILITY_COUNT_COLUMNS},
            totals.total_endpoints, totals.total_hosts
     FROM page pg
     CROSS JOIN totals
     ${mcpCapabilityCountsJoinSql('pg.current_version_id')}
     ORDER BY pg.ord`,
    [MCP_INDEX_PAGE_SIZE, (current - 1) * MCP_INDEX_PAGE_SIZE]
  );

  const groups: McpPublicHostGroup[] = [];
  let group: McpPublicHostGroup | null = null;
  for (const raw of result.rows) {
    // The catalog totals ride on every row; they are not part of an endpoint.
    const row: McpPublicEndpoint & { total_endpoints?: number; total_hosts?: number } = { ...raw };
    delete row.total_endpoints;
    delete row.total_hosts;
    const host = row.host ?? 'Unknown host';
    if (!group || group.host !== host) {
      group = { host, endpoints: [] };
      groups.push(group);
    }
    group.endpoints.push(row);
  }
  const totalEndpoints = result.rows[0]?.total_endpoints ?? 0;
  return {
    groups,
    page: current,
    pageSize: MCP_INDEX_PAGE_SIZE,
    totalEndpoints,
    totalHosts: result.rows[0]?.total_hosts ?? 0,
    hasNext: current * MCP_INDEX_PAGE_SIZE < totalEndpoints,
  };
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
    const result = await dbQuery(
      'getPublicCatalogInsight',
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
 *
 * The capability items are read once (DBP-1.27): the per-type counts on the endpoint are counted
 * from the rows the page lists anyway, where the endpoint statement used to join and group them a
 * first time.
 *
 * @throws DatabaseUnavailableError When the database fails.
 */
export async function getPublicMcpEndpointDetail(
  tenantSlug: string,
  endpointSlug: string
): Promise<McpPublicEndpointDetail | null> {
  noStore();
  const endpointResult = await dbQuery<Omit<McpPublicEndpoint, 'tool_count' | 'resource_count' | 'resource_template_count' | 'prompt_count'>>(
    'getPublicMcpEndpointDetail',
    `SELECT ${MCP_ENDPOINT_COLUMNS}
       FROM apiome.mcp_v_public_endpoints e
       JOIN apiome.tenants t ON t.id = e.tenant_id
      WHERE t.slug = $1 AND e.slug = $2 AND t.deleted_at IS NULL`,
    [tenantSlug, endpointSlug]
  );
  const row = endpointResult.rows[0];
  if (!row) return null;

  const items = row.current_version_id
    ? (
        await dbQuery<McpCapabilityItem>(
          'getPublicMcpEndpointDetail.items',
          `SELECT ci.id, ci.item_type, ci.name, ci.title, ci.description,
                  ci.uri, ci.uri_template, ci.ordinal
             FROM apiome.mcp_capability_items ci
            WHERE ci.version_id = $1
            ORDER BY ci.item_type ASC, ci.ordinal ASC, ci.name ASC`,
          [row.current_version_id]
        )
      ).rows
    : [];

  const count = (type: McpCapabilityItem['item_type']) => items.filter((item) => item.item_type === type).length;
  return {
    endpoint: {
      ...row,
      tool_count: count('tool'),
      resource_count: count('resource'),
      resource_template_count: count('resource_template'),
      prompt_count: count('prompt'),
    },
    items,
  };
}

/**
 * One published curated collection for a tenant, listing only endpoints that pass the public
 * visibility gate (`mcp_v_public_endpoints`). Private or unpublished endpoints in the collection are
 * omitted rather than leaking into anonymous browse (MCAT-22.4).
 *
 * @throws DatabaseUnavailableError When the database fails.
 */
export async function getPublicMcpCollection(
  tenantSlug: string,
  collectionSlug: string
): Promise<McpPublicCollection | null> {
  noStore();
  const collectionResult = await dbQuery<Omit<McpPublicCollection, 'endpoints'>>(
    'getPublicMcpCollection',
    `SELECT c.id, c.tenant_id, t.slug AS tenant_slug, t.name AS tenant_name,
            c.name, c.slug, c.description
       FROM apiome.mcp_collections c
       JOIN apiome.tenants t ON t.id = c.tenant_id AND t.deleted_at IS NULL
      WHERE t.slug = $1 AND c.slug = $2 AND c.is_published IS TRUE
      LIMIT 1`,
    [tenantSlug, collectionSlug]
  );
  const collection = collectionResult.rows[0];
  if (!collection) return null;

  const endpointsResult = await dbQuery<McpPublicEndpoint>(
    'getPublicMcpCollection.endpoints',
    `SELECT ${MCP_ENDPOINT_COLUMNS},
            ${MCP_CAPABILITY_COUNT_COLUMNS}
       FROM apiome.mcp_collection_members m
       JOIN apiome.mcp_v_public_endpoints e ON e.id = m.endpoint_id AND e.tenant_id = m.tenant_id
       JOIN apiome.tenants t ON t.id = e.tenant_id AND t.deleted_at IS NULL
       ${mcpCapabilityCountsJoinSql('e.current_version_id')}
      WHERE m.collection_id = $1::uuid
      ORDER BY m.position ASC, m.added_at ASC, e.name ASC`,
    [collection.id]
  );

  return { ...collection, endpoints: endpointsResult.rows };
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
    const result = await dbQuery(
      'searchPublicMcpCatalog',
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
 * The predicates of `apiome.mcp_v_public_endpoints`, for `apiome.mcp_endpoints` under an alias.
 * Written exactly as the view and the V431 partial indexes write them, so the planner can use
 * those indexes.
 *
 * @param alias - The table alias (written in code).
 * @returns The predicate list.
 */
function mcpPublicEndpointGates(alias: string): string {
  return `${alias}.deleted_at IS NULL AND ${alias}.enabled IS TRUE AND ${alias}.published IS TRUE
              AND ${alias}.visibility = 'public'::apiome.visibility_type`;
}

/**
 * Published public endpoints a registry entry may duplicate (V2-MCP-26.4, #3710).
 *
 * Reads, in one statement, the published endpoints whose registry server name is one of
 * `serverNames` (case-insensitive), whose URL host is one of `hosts`, or whose id is one of
 * `endpointIds` (the catalog hits, so a registry import is labeled even when the search did not
 * return its entry). Only public endpoints qualify; the raw `endpoint_url` is read for the
 * server-side URL comparison and never leaves this process.
 *
 * Three index probes joined by `UNION` (DBP-1.27) — the V431 indexes on the server name and on
 * `lower(host)`, and the primary key — where one `OR` of the three could use none of them.
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
    const result = await dbQuery<McpPublishedEndpointRef>(
      'findPublishedMcpEndpointsForRegistryDedupe',
      `SELECT e.id AS endpoint_id, e.endpoint_url,
              CASE WHEN e.added_via = 'registry' THEN e.registry_metadata->>'serverName' END
                AS registry_server_name
       FROM (
         SELECT n.id FROM apiome.mcp_endpoints n
          WHERE ${mcpPublicEndpointGates('n')}
            AND lower(n.registry_metadata->>'serverName') = ANY($1::text[])
         UNION
         SELECT h.id FROM apiome.mcp_endpoints h
          WHERE ${mcpPublicEndpointGates('h')}
            AND lower(h.host) = ANY($2::text[])
         UNION
         SELECT i.id FROM apiome.mcp_endpoints i
          WHERE ${mcpPublicEndpointGates('i')}
            AND i.id = ANY($3::uuid[])
       ) matched
       JOIN apiome.mcp_endpoints e ON e.id = matched.id`,
      [serverNames.map((n) => n.toLowerCase()), hosts, endpointIds]
    );
    return result.rows;
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
