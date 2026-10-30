/**
 * Re-upload a catalog item's file — RAR-6.2 (#3539).
 *
 * Proxies `POST /v1/catalog/{slug}/{itemId}/reupload`. The body (`{ filename, documentBase64,
 * contentType? }`) is passed through as sent; REST replays the import settings the first upload
 * recorded and answers `status: "changed"` with the new version, or `"unchanged"` when the file
 * matches the current one. Permissions are REST's (`imports:create` and `projects:edit`); a
 * refusal keeps REST's status with `{ success: false, error }`.
 */

import { NextRequest, NextResponse } from 'next/server';
import { CATALOG_UNAVAILABLE, catalogUrl, forwardCatalogRequest, resolveCatalogTenant } from '@lib/catalog-entities-proxy';

export const dynamic = 'force-dynamic';

/** `POST /api/catalog/[itemId]/reupload` — import the new copy of the file with the stored settings. */
export async function POST(request: NextRequest, context: { params: Promise<{ itemId: string }> }) {
  const { itemId } = await context.params;
  const body = await request.json().catch(() => null);
  if (body === null || typeof body !== 'object') {
    return NextResponse.json({ success: false, error: 'Expected a JSON object.' }, { status: 400 });
  }
  const resolved = await resolveCatalogTenant();
  if ('error' in resolved) return resolved.error;
  return forwardCatalogRequest(catalogUrl(resolved.slug, `${encodeURIComponent(itemId)}/reupload`), {
    method: 'POST',
    user: resolved.user,
    body,
    unavailable: CATALOG_UNAVAILABLE,
  });
}
