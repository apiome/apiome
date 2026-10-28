/**
 * The workspace's catalog drift alert settings — MFI-31.3 (#4400).
 *
 * Proxies `GET` / `PUT /v1/catalog/{slug}/drift-notifications`: which drift severities are
 * announced, immediate or daily-digest delivery, whether breaking drift skips the digest, and the
 * stored email opt-in. Permissions are REST's (`projects:view` to read, `imports:edit` to change);
 * a failure keeps REST's status with `{ success: false, error }`.
 */

import { NextRequest, NextResponse } from 'next/server';
import { CATALOG_UNAVAILABLE, catalogUrl, forwardCatalogRequest, resolveCatalogTenant } from '@lib/catalog-entities-proxy';

export const dynamic = 'force-dynamic';

/**
 * Forward one method for the settings resource.
 *
 * @param method The HTTP method to forward.
 * @param body The JSON body for a PUT; omitted otherwise.
 * @returns REST's answer, or the auth / tenant error.
 */
async function forward(method: string, body?: unknown): Promise<NextResponse> {
  const resolved = await resolveCatalogTenant();
  if ('error' in resolved) return resolved.error;
  return forwardCatalogRequest(catalogUrl(resolved.slug, 'drift-notifications'), {
    method,
    user: resolved.user,
    body,
    unavailable: CATALOG_UNAVAILABLE,
  });
}

/** `GET /api/catalog/drift-notifications` — the settings (the defaults when never saved). */
export async function GET() {
  return forward('GET');
}

/** `PUT /api/catalog/drift-notifications` — replace the settings. */
export async function PUT(request: NextRequest) {
  const body = await request.json().catch(() => null);
  if (body === null || typeof body !== 'object' || Array.isArray(body)) {
    return NextResponse.json({ success: false, error: 'Expected a JSON object.' }, { status: 400 });
  }
  return forward('PUT', body);
}
