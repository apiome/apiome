/**
 * `GET /api/search/suggest?q=…` — the search palette's live suggestions.
 *
 * Name matches only (DBP-1.16, #7199): the palette asks on every keystroke, so it gets the bounded,
 * index-driven statement in `lib/search/suggestSql.ts` — organizations, API products, projects,
 * operations, schemas and properties whose *name* matches — not the full catalog search the results
 * page runs. The response carries one short page of the best matches plus per-kind counts, so the
 * palette can offer "see all operations". A count marked `capped` is a floor.
 *
 * Public, read-only, never cached: the catalog changes whenever someone publishes. A statement
 * that runs past the database statement timeout answers `503` with `Retry-After`, never a hung
 * request and never a false "no matches".
 */

import { runCatalogSuggest } from '../../../../../lib/db/search';
import { SearchTimeoutError } from '../../../../../lib/search/errors';
import { resolveSearchRequest } from '../../../../../lib/search/params';
import { sanitizeSearchInput } from '../../../utils/searchValidation';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const SUGGEST_PAGE_SIZE = 8;

/** Seconds a client should wait before asking again after a timeout. */
const RETRY_AFTER_SECONDS = 5;

export async function GET(request: Request): Promise<Response> {
  const url = new URL(request.url);
  const q = sanitizeSearchInput(url.searchParams.get('q') ?? '').trim();
  const scope = url.searchParams.get('scope') ?? undefined;
  const headers = { 'Cache-Control': 'no-store' };

  if (!q) {
    return Response.json(
      { q, rows: [], total: 0, totalAllKinds: 0, truncated: false, kinds: [], tookMs: 0 },
      { headers }
    );
  }

  const resolved = resolveSearchRequest({ q, scope });
  try {
    const response = await runCatalogSuggest({ ...resolved, perPage: SUGGEST_PAGE_SIZE, page: 1 });
    return Response.json(
      {
        q,
        rows: response.rows,
        total: response.total,
        // Suggestions run only the kinds asked for, so both totals are the same number; the field
        // stays for clients written against the earlier response.
        totalAllKinds: response.total,
        truncated: response.truncated,
        kinds: response.kinds,
        tookMs: response.tookMs,
      },
      { headers }
    );
  } catch (err) {
    if (err instanceof SearchTimeoutError) {
      return Response.json(
        { q, error: err.message },
        { status: 503, headers: { ...headers, 'Retry-After': String(RETRY_AFTER_SECONDS) } }
      );
    }
    throw err;
  }
}
