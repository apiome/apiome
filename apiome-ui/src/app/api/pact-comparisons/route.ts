/**
 * The workspace's recent bi-directional comparisons — PFX-2.5 (#6929).
 *
 * Proxies `GET /v1/tenants/{slug}/pact-comparisons`, passing `limit` on only when it is a whole
 * number in 1 … 100. Permissions (`pacts:view`) are REST's.
 */

import { NextRequest } from 'next/server';
import { forwardConnectorRequest, resolveConnectorTenant, tenantUrl } from '@lib/connectors-proxy';
import { listProxyPath } from '@lib/pact-comparisons';

export const dynamic = 'force-dynamic';

/** What the browser is told when apiome-rest cannot be reached. */
const UNAVAILABLE = 'Pact comparisons are unavailable (apiome-rest not reachable). Try again shortly.';

export async function GET(request: NextRequest) {
  const resolved = await resolveConnectorTenant();
  if ('error' in resolved) return resolved.error;
  const path = listProxyPath(request.nextUrl.searchParams.get('limit'));
  return forwardConnectorRequest(tenantUrl(resolved.slug, path), {
    method: 'GET',
    user: resolved.user,
    unavailable: UNAVAILABLE,
  });
}
