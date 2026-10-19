/**
 * The catalog home's kind counts and callouts — CDG-5.1 (#5979).
 *
 * Proxies `GET /v1/catalog/{slug}/entities/summary?team=&q=`.
 */

import { NextRequest } from 'next/server';
import { entityQuery } from '@lib/catalog-entities';
import { CATALOG_UNAVAILABLE, catalogUrl, forwardCatalogRequest, resolveCatalogTenant } from '@lib/catalog-entities-proxy';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  const resolved = await resolveCatalogTenant();
  if ('error' in resolved) return resolved.error;
  const query = entityQuery(request.nextUrl.searchParams, ['team', 'q']);
  return forwardCatalogRequest(catalogUrl(resolved.slug, `entities/summary${query}`), {
    method: 'GET',
    user: resolved.user,
    unavailable: CATALOG_UNAVAILABLE,
  });
}
