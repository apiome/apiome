'use server';

/**
 * Run the catalog search (see `lib/search/sql.ts`) against the browse database.
 *
 * Server-only: it owns the pool, the timing, and the failure contract. A failing statement is
 * logged and renders as an empty result with the same shape — except one that PostgreSQL cancelled
 * for running past the pool's `statement_timeout`: that is thrown as a `SearchTimeoutError`,
 * so the visitor gets an error page (or the palette a 503) instead of a false "no results"
 * (DBP-1.16, #7199).
 */

import { unstable_noStore as noStore } from 'next/cache';
import connectionPool, { isStatementTimeout } from './db';
import { dbQuery } from './query';
import { searchFacetCache } from './ttlCache';
import { emptySearchResponse, type CatalogSearchHit, type CatalogSearchResponse, type FacetBucket, type ProjectFacet } from '../search/hits';
import { SearchTimeoutError } from '../search/errors';
import { isEmptyRequest, toSearchParams, toUrlState, type SearchRequest } from '../search/params';
import { SEARCH_KIND_CAP, buildCatalogSearchSql } from '../search/sql';
import { SUGGEST_MEMBER_CAP, buildSuggestSql } from '../search/suggestSql';
import {
  HIT_VERSIONS_ALL_CAP,
  buildHitVersionsSql,
  type HitVersion,
  type HitVersionCounts,
  type HitVersionsMap,
} from '../search/compare';

interface SearchRow {
  total: number;
  total_all_kinds: number;
  kind_facets: FacetBucket[];
  org_facets: FacetBucket[];
  method_facets: FacetBucket[];
  format_facets: FacetBucket[];
  paradigm_facets: FacetBucket[];
  severity_facets: FacetBucket[];
  project_facets: ProjectFacet[];
  rows: CatalogSearchHit[];
}

type SearchFacets = CatalogSearchResponse['facets'];

/** The filter facets of a result row (everything in the rail except the per-kind counts). */
function filterFacetsOf(row: SearchRow): Omit<SearchFacets, 'kinds'> {
  return {
    orgs: row.org_facets ?? [],
    methods: row.method_facets ?? [],
    formats: row.format_facets ?? [],
    paradigms: row.paradigm_facets ?? [],
    severities: row.severity_facets ?? [],
    projects: row.project_facets ?? [],
  };
}

/** What a search's first page computes for all its pages: the filter facets and the per-kind counts. */
interface CachedSearchFacets {
  filters: Omit<SearchFacets, 'kinds'>;
  kinds: FacetBucket[];
  totalAllKinds: number;
}

/** A key for "this search, whatever the page": the request's URL form without `page`. */
function facetCacheKey(request: SearchRequest): string {
  return toSearchParams(toUrlState({ ...request, page: 1 }));
}

/**
 * Execute a search request.
 *
 * The filter facets and the per-kind counts (the scope tabs) describe the whole result set, so they
 * are the same on every page. They are computed with the first page and kept in the facet cache; a
 * later page of the same search reuses them, and its statement skips the facet aggregates and runs
 * only the kinds it lists (DBP-1.27). A later page that arrives with nothing cached (a shared deep
 * link, another Browse instance, an expired entry) computes them itself, so the rail and the tabs
 * are never empty.
 *
 * @param request The resolved request.
 * @returns The response; empty (not an error) for an empty request, an un-runnable combination of
 *   filters, or a database failure other than a timeout.
 * @throws SearchTimeoutError when the statement was cancelled by `statement_timeout`.
 */
export async function runCatalogSearch(request: SearchRequest): Promise<CatalogSearchResponse> {
  noStore();
  if (isEmptyRequest(request)) return emptySearchResponse(request.page, request.perPage);
  if (!buildCatalogSearchSql(request)) return emptySearchResponse(request.page, request.perPage);

  const started = performance.now();
  const key = facetCacheKey(request);
  try {
    /** Run the statement, with or without the facet aggregates and the other kinds' counts. */
    const run = async (facets: boolean): Promise<SearchRow | undefined> => {
      const statement = buildCatalogSearchSql(request, { facets, otherKindCounts: facets });
      if (!statement) return undefined;
      const result = await connectionPool.query<SearchRow>(statement.text, statement.values);
      return result.rows[0];
    };

    // Page 1 always computes the facets; a later page reuses them when this process has them.
    const cached = request.page > 1 ? searchFacetCache.peek<CachedSearchFacets>(key) : undefined;
    const row = await run(!cached);
    if (!row) return emptySearchResponse(request.page, request.perPage);
    const facets: CachedSearchFacets = cached?.value ?? {
      filters: filterFacetsOf(row),
      kinds: row.kind_facets ?? [],
      totalAllKinds: Number(row.total_all_kinds) || 0,
    };
    if (!cached) searchFacetCache.store(key, facets);

    const total = Number(row.total) || 0;
    return {
      total,
      totalAllKinds: facets.totalAllKinds,
      // A kind that reached its cap has more hits than were counted.
      truncated: facets.kinds.some((bucket) => bucket.count >= SEARCH_KIND_CAP),
      page: request.page,
      perPage: request.perPage,
      pageCount: Math.max(0, Math.ceil(total / request.perPage)),
      rows: Array.isArray(row.rows) ? row.rows : [],
      facets: { kinds: facets.kinds, ...facets.filters },
      tookMs: Math.round(performance.now() - started),
    };
  } catch (err) {
    const e = err as { message?: string };
    console.error('[db] runCatalogSearch:', e?.message ?? err);
    if (isStatementTimeout(err)) throw new SearchTimeoutError();
    return emptySearchResponse(request.page, request.perPage);
  }
}

/** What the palette gets back for one keystroke. */
interface CatalogSuggestResponse {
  /** The best name matches, at most `request.perPage`. */
  rows: CatalogSearchHit[];
  /** Hits found across the suggested kinds; a floor when `truncated`. */
  total: number;
  /** True when a kind reached its cap, so `total` and that kind's count are floors. */
  truncated: boolean;
  /** Hits per kind, most first; `capped` marks a count that is a floor ("40+"). */
  kinds: FacetBucket[];
  tookMs: number;
}

interface SuggestRow {
  total: number;
  kind_facets: FacetBucket[];
  rows: CatalogSearchHit[];
}

const EMPTY_SUGGESTIONS: CatalogSuggestResponse = { rows: [], total: 0, truncated: false, kinds: [], tookMs: 0 };

/**
 * Run the palette's name-only suggestion statement (see `lib/search/suggestSql.ts`).
 *
 * @param request The resolved request; `perPage` is how many suggestions to return.
 * @returns The suggestions; empty (not an error) for an empty request, a request no suggestable
 *   kind can honour, or a database failure other than a timeout.
 * @throws SearchTimeoutError when the statement was cancelled by `statement_timeout`.
 */
export async function runCatalogSuggest(request: SearchRequest): Promise<CatalogSuggestResponse> {
  noStore();
  if (isEmptyRequest(request)) return EMPTY_SUGGESTIONS;
  const statement = buildSuggestSql(request);
  if (!statement) return EMPTY_SUGGESTIONS;

  const started = performance.now();
  try {
    const result = await connectionPool.query<SuggestRow>(statement.text, statement.values);
    const row = result.rows[0];
    if (!row) return EMPTY_SUGGESTIONS;
    // A kind that filled its cap has more matches than were read: report the cap as a floor.
    const kinds = (row.kind_facets ?? []).map((bucket) =>
      bucket.count >= SUGGEST_MEMBER_CAP ? { ...bucket, count: SUGGEST_MEMBER_CAP, capped: true } : bucket
    );
    return {
      rows: Array.isArray(row.rows) ? row.rows : [],
      total: kinds.reduce((sum, bucket) => sum + bucket.count, 0),
      truncated: kinds.some((bucket) => bucket.capped),
      kinds,
      tookMs: Math.round(performance.now() - started),
    };
  } catch (err) {
    const e = err as { message?: string };
    console.error('[db] runCatalogSuggest:', e?.message ?? err);
    if (isStatementTimeout(err)) throw new SearchTimeoutError();
    return EMPTY_SUGGESTIONS;
  }
}

/** What {@link runHitVersionsLookup} returns for a page of hits. */
export interface HitVersionsLookup {
  /** hit_id → its project's newest versions, newest first. */
  versions: HitVersionsMap;
  /** hit_id → how many published public versions its project has in all. */
  counts: HitVersionCounts;
}

/** One row of the hit-versions statement. */
interface HitVersionsRow {
  hit_id: string;
  version_count: number;
  versions: HitVersion[] | null;
}

/** Fold the statement's rows into the two maps. */
function toHitVersionsLookup(rows: readonly HitVersionsRow[]): HitVersionsLookup {
  const lookup: HitVersionsLookup = { versions: {}, counts: {} };
  for (const row of rows) {
    lookup.versions[row.hit_id] = Array.isArray(row.versions) ? row.versions : [];
    lookup.counts[row.hit_id] = Number(row.version_count) || 0;
  }
  return lookup;
}

/**
 * Look up the version quick-switch menus for a page of hits (BDX-2.6): each eligible hit's
 * project's newest published versions (at most `HIT_VERSIONS_CAP`), whether its operation or schema
 * exists in each, and how many versions the project has in all — so a menu can offer the rest.
 *
 * @param rows The page's rows (only version / operation / schema hits are looked up).
 * @returns The menus; empty when nothing is eligible or the lookup fails (the menus then simply do
 *   not render — never a 500).
 */
export async function runHitVersionsLookup(rows: readonly CatalogSearchHit[]): Promise<HitVersionsLookup> {
  noStore();
  const statement = buildHitVersionsSql(rows);
  if (!statement) return { versions: {}, counts: {} };
  try {
    const result = await connectionPool.query<HitVersionsRow>(statement.text, statement.values);
    return toHitVersionsLookup(result.rows);
  } catch (err) {
    const e = err as { message?: string };
    console.error('[db] runHitVersionsLookup:', e?.message ?? err);
    return { versions: {}, counts: {} };
  }
}

/**
 * Every published public version of one hit's project (at most `HIT_VERSIONS_ALL_CAP`), for a menu
 * whose visitor asked for the versions the page did not list (DBP-1.27).
 *
 * @param hit The hit, as the page has it.
 * @returns Its versions, newest first; empty when the hit is not eligible or its project is not public.
 * @throws DatabaseUnavailableError When the database fails.
 */
export async function runAllHitVersions(hit: CatalogSearchHit): Promise<HitVersion[]> {
  noStore();
  const statement = buildHitVersionsSql([hit], HIT_VERSIONS_ALL_CAP);
  if (!statement) return [];
  const result = await dbQuery<HitVersionsRow>('runAllHitVersions', statement.text, statement.values);
  return toHitVersionsLookup(result.rows).versions[hit.hit_id] ?? [];
}
