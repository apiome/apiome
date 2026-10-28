/**
 * Dismiss a catalog item's drift — MFI-31.3 (#4400).
 *
 * Proxies `POST /v1/catalog/{slug}/{itemId}/drift/{eventId}/dismiss` (`projects:edit`): the badge
 * and banner go away; the event and its changes are kept.
 */

import { NextRequest, NextResponse } from 'next/server';
import { CATALOG_UNAVAILABLE, catalogUrl, forwardCatalogRequest, resolveCatalogTenant } from '@lib/catalog-entities-proxy';

export const dynamic = 'force-dynamic';

type Context = { params: Promise<{ itemId: string; eventId: string }> };

/** `POST /api/catalog/[itemId]/drift/[eventId]/dismiss` — dismiss one event. */
export async function POST(_request: NextRequest, context: Context): Promise<NextResponse> {
  const { itemId, eventId } = await context.params;
  const resolved = await resolveCatalogTenant();
  if ('error' in resolved) return resolved.error;
  return forwardCatalogRequest(
    catalogUrl(resolved.slug, `${encodeURIComponent(itemId)}/drift/${encodeURIComponent(eventId)}/dismiss`),
    { method: 'POST', user: resolved.user, unavailable: CATALOG_UNAVAILABLE },
  );
}
