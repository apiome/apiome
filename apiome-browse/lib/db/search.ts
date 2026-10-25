'use server';

/**
 * Run the catalog search (see `lib/search/sql.ts`) against the browse database.
 *
 * Server-only: it owns the pool, the timing, and the fail-soft contract (a failing statement is
 * logged and renders as an empty result with the same shape, never a 500 for a visitor).
 */

import { unstable_noStore as noStore } from 'next/cache';
import connectionPool from './db';
import { emptySearchResponse, type CatalogSearchHit, type CatalogSearchResponse, type FacetBucket, type ProjectFacet } from '../search/hits';
import { isEmptyRequest, type SearchRequest } from '../search/params';
import { SEARCH_HIT_CAP, buildCatalogSearchSql } from '../search/sql';

interface SearchRow {
  total: number;
  total_all_kinds: number;
  kind_facets: FacetBucket[];
  org_facets: FacetBucket[];
  method_facets: FacetBucket[];
  format_facets: FacetBucket[];
  paradigm_facets: FacetBucket[];
  project_facets: ProjectFacet[];
  rows: CatalogSearchHit[];
}

/**
 * Execute a search request.
 *
 * @param request The resolved request.
 * @returns The response; empty (not an error) for an empty request, an un-runnable combination of
 *   filters, or a database failure.
 */
export async function runCatalogSearch(request: SearchRequest): Promise<CatalogSearchResponse> {
  noStore();
  if (isEmptyRequest(request)) return emptySearchResponse(request.page, request.perPage);
  const statement = buildCatalogSearchSql(request);
  if (!statement) return emptySearchResponse(request.page, request.perPage);

  const started = performance.now();
  try {
    const result = await connectionPool.query<SearchRow>(statement.text, statement.values);
    const row = result.rows[0];
    if (!row) return emptySearchResponse(request.page, request.perPage);
    const total = Number(row.total) || 0;
    const totalAllKinds = Number(row.total_all_kinds) || 0;
    return {
      total,
      totalAllKinds,
      truncated: totalAllKinds >= SEARCH_HIT_CAP,
      page: request.page,
      perPage: request.perPage,
      pageCount: Math.max(0, Math.ceil(total / request.perPage)),
      rows: Array.isArray(row.rows) ? row.rows : [],
      facets: {
        kinds: row.kind_facets ?? [],
        orgs: row.org_facets ?? [],
        methods: row.method_facets ?? [],
        formats: row.format_facets ?? [],
        paradigms: row.paradigm_facets ?? [],
        projects: row.project_facets ?? [],
      },
      tookMs: Math.round(performance.now() - started),
    };
  } catch (err) {
    const e = err as { message?: string };
    console.error('[db] runCatalogSearch:', e?.message ?? err);
    return emptySearchResponse(request.page, request.perPage);
  }
}
