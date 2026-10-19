/**
 * One catalog entity's facts — CDG-5.4 (#5982).
 *
 * Proxies `GET /v1/catalog/{slug}/entities/{kind}/{id}/facts`; a malformed kind or id is a 404
 * without calling apiome-rest. Permissions are REST's.
 */

import { NextRequest, NextResponse } from 'next/server';
import { factsProxyPath } from '@lib/catalog-facts';
import { CATALOG_UNAVAILABLE, catalogUrl, forwardCatalogRequest, resolveCatalogTenant } from '@lib/catalog-entities-proxy';

export const dynamic = 'force-dynamic';

export async function GET(_request: NextRequest, context: { params: Promise<{ kind: string; id: string }> }) {
  const { kind, id } = await context.params;
  const path = factsProxyPath(kind, id);
  if (path === null) return NextResponse.json({ success: false, error: 'Unknown entity.' }, { status: 404 });
  const resolved = await resolveCatalogTenant();
  if ('error' in resolved) return resolved.error;
  return forwardCatalogRequest(catalogUrl(resolved.slug, path), {
    method: 'GET',
    user: resolved.user,
    unavailable: CATALOG_UNAVAILABLE,
  });
}
