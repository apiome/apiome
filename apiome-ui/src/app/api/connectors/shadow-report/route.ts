/**
 * Shadow-API report (CDG-1.6, #5957).
 *
 * Proxies `GET /v1/tenants/{slug}/shadow-report?connector=&environment=`. Auth and forwarding only;
 * the shared halves live in `@lib/connectors-proxy`.
 */

import { NextRequest } from 'next/server';
import { forwardConnectorRequest, resolveConnectorTenant, tenantUrl } from '@lib/connectors-proxy';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  const resolved = await resolveConnectorTenant();
  if ('error' in resolved) return resolved.error;
  const query = new URLSearchParams();
  for (const key of ['connector', 'environment']) {
    const value = request.nextUrl.searchParams.get(key);
    if (value) query.set(key, value);
  }
  const suffix = query.toString() ? `?${query.toString()}` : '';
  return forwardConnectorRequest(tenantUrl(resolved.slug, `shadow-report${suffix}`), {
    method: 'GET',
    user: resolved.user,
  });
}
