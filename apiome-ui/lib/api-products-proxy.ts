/**
 * Forwarding for `/api/products/…` — APX-1.1 (#6098).
 *
 * Only the paths and methods {@link productProxyPath} allows are forwarded, and a write carries only
 * its own fields ({@link productProxyBody}). Permissions (`projects:view|create|edit|delete`) are
 * apiome-rest's.
 */

import { NextRequest, NextResponse } from 'next/server';
import { forwardConnectorRequest, resolveConnectorTenant, tenantUrl } from '@lib/connectors-proxy';
import { productProxyBody, productProxyPath, type ProductProxyMethod } from '@lib/api-products';

/** What the browser is told when apiome-rest cannot be reached. */
const UNAVAILABLE = 'API products are unavailable (apiome-rest not reachable). Try again shortly.';

/**
 * Forward one allowed request.
 *
 * @param request - The browser's request.
 * @param segments - The path segments after `/api/products`.
 * @param method - The HTTP method.
 * @returns REST's answer, or `404` for a path the proxy does not forward.
 */
export async function forwardApiProducts(
  request: NextRequest,
  segments: readonly string[] | undefined,
  method: ProductProxyMethod,
): Promise<NextResponse> {
  const path = productProxyPath(segments ?? [], method);
  if (path === null) {
    return NextResponse.json({ success: false, error: 'Unknown path.' }, { status: 404 });
  }
  const resolved = await resolveConnectorTenant();
  if ('error' in resolved) return resolved.error;
  const body =
    method === 'POST' || method === 'PATCH'
      ? productProxyBody(path, method, await request.json().catch(() => ({})))
      : undefined;
  return forwardConnectorRequest(tenantUrl(resolved.slug, path), {
    method,
    user: resolved.user,
    body,
    unavailable: UNAVAILABLE,
  });
}
