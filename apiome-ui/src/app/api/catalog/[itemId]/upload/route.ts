/**
 * A catalog item's upload state — RAR-6.2 (#3539).
 *
 * Proxies `GET /v1/catalog/{slug}/{itemId}/upload`: whether the item's newest version came from a
 * file upload, how old it is, whether that is past the workspace's threshold (it "may be stale"),
 * and the import settings a re-upload replays. Permissions are REST's (`projects:view`).
 */

import { NextRequest } from 'next/server';
import { CATALOG_UNAVAILABLE, catalogUrl, forwardCatalogRequest, resolveCatalogTenant } from '@lib/catalog-entities-proxy';

export const dynamic = 'force-dynamic';

/** `GET /api/catalog/[itemId]/upload` — the item's upload state. */
export async function GET(_request: NextRequest, context: { params: Promise<{ itemId: string }> }) {
  const { itemId } = await context.params;
  const resolved = await resolveCatalogTenant();
  if ('error' in resolved) return resolved.error;
  return forwardCatalogRequest(catalogUrl(resolved.slug, `${encodeURIComponent(itemId)}/upload`), {
    method: 'GET',
    user: resolved.user,
    unavailable: CATALOG_UNAVAILABLE,
  });
}
