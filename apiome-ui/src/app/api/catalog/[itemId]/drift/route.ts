/**
 * A catalog item's drift events — MFI-31.3 (#4400).
 *
 * Proxies `GET /v1/catalog/{slug}/{itemId}/drift`: each version a live refresh added, graded
 * safe / dangerous / breaking, with its classified changes, newest first (`projects:view`).
 */

import { NextRequest, NextResponse } from 'next/server';
import { CATALOG_UNAVAILABLE, catalogUrl, forwardCatalogRequest, resolveCatalogTenant } from '@lib/catalog-entities-proxy';

export const dynamic = 'force-dynamic';

type Context = { params: Promise<{ itemId: string }> };

/** `GET /api/catalog/[itemId]/drift` — the item's drift events. */
export async function GET(_request: NextRequest, context: Context): Promise<NextResponse> {
  const { itemId } = await context.params;
  const resolved = await resolveCatalogTenant();
  if ('error' in resolved) return resolved.error;
  return forwardCatalogRequest(catalogUrl(resolved.slug, `${encodeURIComponent(itemId)}/drift`), {
    method: 'GET',
    user: resolved.user,
    unavailable: CATALOG_UNAVAILABLE,
  });
}
