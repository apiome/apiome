/**
 * Shared forwarding for the `/api/catalog-agents` and `/api/catalog-models` routes — CDG-5.2 (#5980).
 *
 * Only the paths and methods {@link catalogAgentProxyPath} allows are forwarded, and a write carries
 * only its own fields ({@link catalogAgentProxyBody}). Permissions (`consumer_contracts:*`, plus
 * `api_keys:view` to link a key) are apiome-rest's.
 */

import { NextRequest, NextResponse } from 'next/server';
import { forwardConnectorRequest, resolveConnectorTenant, tenantUrl } from '@lib/connectors-proxy';
import { catalogAgentProxyBody, catalogAgentProxyPath, type CatalogAgentMethod } from '@lib/catalog-agents';

/** What the browser is told when apiome-rest cannot be reached. */
const UNAVAILABLE = 'The agent catalog is unavailable (apiome-rest not reachable). Try again shortly.';

/**
 * Forward one allowed request.
 *
 * @param collection - `catalog-agents` or `catalog-models`.
 * @param request - The browser's request.
 * @param segments - The path segments after the collection (none for the list).
 * @param method - The HTTP method.
 * @returns REST's answer, or `404` for a path the proxy does not forward.
 */
export async function forwardCatalogAgents(
  collection: 'catalog-agents' | 'catalog-models',
  request: NextRequest,
  segments: readonly string[] | undefined,
  method: CatalogAgentMethod,
): Promise<NextResponse> {
  const path = catalogAgentProxyPath(collection, segments ?? [], method);
  if (path === null) {
    return NextResponse.json({ success: false, error: 'Unknown path.' }, { status: 404 });
  }
  const resolved = await resolveConnectorTenant();
  if ('error' in resolved) return resolved.error;
  const body =
    method === 'POST' || method === 'PATCH'
      ? catalogAgentProxyBody(collection, await request.json().catch(() => ({})))
      : undefined;
  const response = await forwardConnectorRequest(tenantUrl(resolved.slug, path), {
    method,
    user: resolved.user,
    body,
    unavailable: UNAVAILABLE,
  });
  // A 204 (delete) comes back from the forwarder as `{}`; keep it a 204 for the browser.
  if (method === 'DELETE' && response.ok && segments?.length === 1) return new NextResponse(null, { status: 204 });
  return response;
}
