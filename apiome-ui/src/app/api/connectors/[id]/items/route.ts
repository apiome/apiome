/**
 * A connector's inventory (CDG-1.7, #5958). Proxies `GET /v1/tenants/{slug}/connectors/{id}/items`
 * with its `status`, `limit` and `offset` query.
 */

import { NextRequest } from 'next/server';
import { forwardConnectorRequest, resolveConnectorTenant, tenantUrl } from '@lib/connectors-proxy';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const resolved = await resolveConnectorTenant();
  if ('error' in resolved) return resolved.error;
  const query = new URLSearchParams();
  for (const key of ['status', 'limit', 'offset']) {
    const value = request.nextUrl.searchParams.get(key);
    if (value) query.set(key, value);
  }
  const suffix = query.toString() ? `?${query.toString()}` : '';
  return forwardConnectorRequest(tenantUrl(resolved.slug, `connectors/${encodeURIComponent(id)}/items${suffix}`), {
    method: 'GET',
    user: resolved.user,
  });
}
