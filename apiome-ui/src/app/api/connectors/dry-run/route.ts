/**
 * Connector dry run (CDG-1.7, #5958): ask the provider what a connector would sync, storing nothing.
 *
 * Proxies `POST /v1/tenants/{slug}/connectors/dry-run`. The body carries credentials for this one call;
 * the proxy forwards them and keeps nothing. A static sibling of `[id]`, so it never collides with it.
 */

import { NextRequest } from 'next/server';
import { forwardConnectorRequest, resolveConnectorTenant, tenantUrl } from '@lib/connectors-proxy';

export const dynamic = 'force-dynamic';

export async function POST(request: NextRequest) {
  const resolved = await resolveConnectorTenant();
  if ('error' in resolved) return resolved.error;
  const body = await request.json().catch(() => ({}));
  return forwardConnectorRequest(tenantUrl(resolved.slug, 'connectors/dry-run'), {
    method: 'POST',
    user: resolved.user,
    body,
  });
}
