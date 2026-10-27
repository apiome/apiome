/**
 * Check a catalog item's live source now — MFI-31.1 (#4398).
 *
 * Proxies `POST /v1/catalog/{slug}/{itemId}/refresh/check`. A failed check is a 200 carrying
 * `status: "failed"` and `lastError`; a 409 means refresh is off for the item or switched off for
 * the workspace. Permissions are REST's (`projects:edit`).
 */

import { NextRequest } from 'next/server';
import { CATALOG_UNAVAILABLE, catalogUrl, forwardCatalogRequest, resolveCatalogTenant } from '@lib/catalog-entities-proxy';

export const dynamic = 'force-dynamic';

/** `POST /api/catalog/[itemId]/refresh/check` — run one check and return the recorded outcome. */
export async function POST(_request: NextRequest, context: { params: Promise<{ itemId: string }> }) {
  const { itemId } = await context.params;
  const resolved = await resolveCatalogTenant();
  if ('error' in resolved) return resolved.error;
  return forwardCatalogRequest(catalogUrl(resolved.slug, `${encodeURIComponent(itemId)}/refresh/check`), {
    method: 'POST',
    user: resolved.user,
    unavailable: CATALOG_UNAVAILABLE,
  });
}
