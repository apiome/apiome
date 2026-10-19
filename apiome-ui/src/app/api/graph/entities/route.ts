/**
 * Tenant-wide graph entity search (CDG-3.4, #5969).
 *
 * Proxies `GET /v1/graph/{slug}/entities?q=&kind=&team=&provenance=&limit=&offset=`.
 */

import { NextRequest } from 'next/server';
import { forwardGraphRequest, forwardedQuery, graphUrl, resolveGraphTenant } from '@lib/graph-proxy';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  const resolved = await resolveGraphTenant();
  if ('error' in resolved) return resolved.error;
  const query = forwardedQuery(request.nextUrl.searchParams, {
    q: 'single',
    kind: 'repeat',
    team: 'single',
    provenance: 'repeat',
    limit: 'single',
    offset: 'single',
  });
  return forwardGraphRequest(graphUrl(resolved.slug, `entities${query}`), {
    method: 'GET',
    user: resolved.user,
    unavailable: 'The dependency graph is unavailable right now.',
  });
}
