/**
 * `GET /api/search/suggest?q=…` — the search palette's live suggestions.
 *
 * The same engine as the results page (`lib/search`), asked for one short page of the best
 * matches across the latest published public versions, plus the per-kind counts so the palette
 * can offer "see all N operations". Public, read-only, never cached: the catalog changes whenever
 * someone publishes.
 */

import { runCatalogSearch } from '../../../../../lib/db/search';
import { resolveSearchRequest } from '../../../../../lib/search/params';
import { sanitizeSearchInput } from '../../../utils/searchValidation';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const SUGGEST_PAGE_SIZE = 8;

export async function GET(request: Request): Promise<Response> {
  const url = new URL(request.url);
  const q = sanitizeSearchInput(url.searchParams.get('q') ?? '').trim();
  const scope = url.searchParams.get('scope') ?? undefined;
  const headers = { 'Cache-Control': 'no-store' };

  if (!q) {
    return Response.json({ q, rows: [], total: 0, totalAllKinds: 0, kinds: [], tookMs: 0 }, { headers });
  }

  const resolved = resolveSearchRequest({ q, scope });
  const response = await runCatalogSearch({ ...resolved, perPage: SUGGEST_PAGE_SIZE, page: 1 });
  return Response.json(
    {
      q,
      rows: response.rows,
      total: response.total,
      totalAllKinds: response.totalAllKinds,
      kinds: response.facets.kinds,
      tookMs: response.tookMs,
    },
    { headers }
  );
}
