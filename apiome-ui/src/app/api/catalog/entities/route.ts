/**
 * The unified catalog entity list — CDG-5.1 (#5979).
 *
 * Proxies `GET /v1/catalog/{slug}/entities?kind=&team=&q=&cursor=&limit=`; only those parameters,
 * well-formed, are forwarded. Which kinds the caller may view is REST's decision.
 */

import { NextRequest } from 'next/server';
import { entityQuery } from '@lib/catalog-entities';
import { CATALOG_UNAVAILABLE, catalogUrl, forwardCatalogRequest, resolveCatalogTenant } from '@lib/catalog-entities-proxy';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  const resolved = await resolveCatalogTenant();
  if ('error' in resolved) return resolved.error;
  return forwardCatalogRequest(catalogUrl(resolved.slug, `entities${entityQuery(request.nextUrl.searchParams)}`), {
    method: 'GET',
    user: resolved.user,
    unavailable: CATALOG_UNAVAILABLE,
  });
}
