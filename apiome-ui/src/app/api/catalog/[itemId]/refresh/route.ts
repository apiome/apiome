/**
 * A catalog item's live-source refresh setting — MFI-31.1 (#4398).
 *
 * Proxies `GET` / `PUT` / `DELETE /v1/catalog/{slug}/{itemId}/refresh`. The body of a PUT is passed
 * through as sent (`{ cadence, adapter, endpoint, options, credential? }`); REST validates it,
 * seals any credential and never returns it. Permissions are REST's (`projects:view` to read,
 * `projects:edit` to change); a failure keeps REST's status with `{ success: false, error }`.
 */

import { NextRequest, NextResponse } from 'next/server';
import { CATALOG_UNAVAILABLE, catalogUrl, forwardCatalogRequest, resolveCatalogTenant } from '@lib/catalog-entities-proxy';

export const dynamic = 'force-dynamic';

type Context = { params: Promise<{ itemId: string }> };

/**
 * Forward one method for the item's refresh resource.
 *
 * @param context The route params (`itemId`).
 * @param method The HTTP method to forward.
 * @param body The JSON body for a PUT; omitted otherwise.
 * @returns REST's answer, or the auth / tenant error.
 */
async function forward(context: Context, method: string, body?: unknown): Promise<NextResponse> {
  const { itemId } = await context.params;
  const resolved = await resolveCatalogTenant();
  if ('error' in resolved) return resolved.error;
  return forwardCatalogRequest(catalogUrl(resolved.slug, `${encodeURIComponent(itemId)}/refresh`), {
    method,
    user: resolved.user,
    body,
    unavailable: CATALOG_UNAVAILABLE,
  });
}

/** `GET /api/catalog/[itemId]/refresh` — the setting and last check (`configured: false` when none). */
export async function GET(_request: NextRequest, context: Context) {
  return forward(context, 'GET');
}

/** `PUT /api/catalog/[itemId]/refresh` — create or replace the setting. */
export async function PUT(request: NextRequest, context: Context) {
  const body = await request.json().catch(() => null);
  if (body === null || typeof body !== 'object') {
    return NextResponse.json({ success: false, error: 'Expected a JSON object.' }, { status: 400 });
  }
  return forward(context, 'PUT', body);
}

/** `DELETE /api/catalog/[itemId]/refresh` — remove the setting and its credential. */
export async function DELETE(_request: NextRequest, context: Context) {
  return forward(context, 'DELETE');
}
