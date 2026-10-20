/**
 * Forwarding for `/api/catalog-migrations/…` — CDG-5.5 (#5983).
 *
 * Only the paths and methods {@link catalogMigrationProxyPath} allows are forwarded, and a write
 * carries only its own fields ({@link catalogMigrationProxyBody}). Permissions (`imports:view|create`,
 * plus `teams:create` to accept a team) are apiome-rest's.
 */

import { NextRequest, NextResponse } from 'next/server';
import { forwardConnectorRequest, resolveConnectorTenant, tenantUrl } from '@lib/connectors-proxy';
import { catalogMigrationProxyBody, catalogMigrationProxyPath, type CatalogMigrationMethod } from '@lib/catalog-migrations';

/** What the browser is told when apiome-rest cannot be reached. */
const UNAVAILABLE = 'Catalog imports are unavailable (apiome-rest not reachable). Try again shortly.';

/**
 * Forward one allowed request.
 *
 * @param request - The browser's request.
 * @param segments - The path segments after `/api/catalog-migrations`.
 * @param method - The HTTP method.
 * @returns REST's answer, or `404` for a path the proxy does not forward.
 */
export async function forwardCatalogMigrations(
  request: NextRequest,
  segments: readonly string[] | undefined,
  method: CatalogMigrationMethod,
): Promise<NextResponse> {
  const path = catalogMigrationProxyPath(segments ?? [], method);
  if (path === null) {
    return NextResponse.json({ success: false, error: 'Unknown path.' }, { status: 404 });
  }
  const resolved = await resolveConnectorTenant();
  if ('error' in resolved) return resolved.error;
  const body = method === 'POST' ? catalogMigrationProxyBody(path, await request.json().catch(() => ({}))) : undefined;
  return forwardConnectorRequest(tenantUrl(resolved.slug, path), {
    method,
    user: resolved.user,
    body,
    unavailable: UNAVAILABLE,
  });
}
