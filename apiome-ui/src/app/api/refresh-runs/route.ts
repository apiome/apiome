/**
 * The refresh ledger (CDG-1.7, #5958): Git refresh jobs and connector runs, interleaved.
 *
 * Proxies `GET /v1/tenants/{slug}/refresh-runs` with its `connector`, `source`, `limit` and `offset`
 * query.
 */

import { NextRequest } from 'next/server';
import { forwardConnectorRequest, resolveConnectorTenant, tenantUrl } from '@lib/connectors-proxy';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  const resolved = await resolveConnectorTenant();
  if ('error' in resolved) return resolved.error;
  const query = new URLSearchParams();
  for (const key of ['connector', 'source', 'limit', 'offset']) {
    const value = request.nextUrl.searchParams.get(key);
    if (value) query.set(key, value);
  }
  const suffix = query.toString() ? `?${query.toString()}` : '';
  return forwardConnectorRequest(tenantUrl(resolved.slug, `refresh-runs${suffix}`), {
    method: 'GET',
    user: resolved.user,
  });
}
