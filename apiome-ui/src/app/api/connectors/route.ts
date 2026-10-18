/**
 * Catalog connectors (CDG-1.7, #5958): list and register.
 *
 * Proxies `GET` / `POST /v1/tenants/{slug}/connectors`. Auth and forwarding only; the shared halves
 * live in `@lib/connectors-proxy`, and the `imports` permission is REST's.
 */

import { NextRequest } from 'next/server';
import { forwardConnectorRequest, resolveConnectorTenant, tenantUrl } from '@lib/connectors-proxy';

export const dynamic = 'force-dynamic';

export async function GET() {
  const resolved = await resolveConnectorTenant();
  if ('error' in resolved) return resolved.error;
  return forwardConnectorRequest(tenantUrl(resolved.slug, 'connectors'), { method: 'GET', user: resolved.user });
}

export async function POST(request: NextRequest) {
  const resolved = await resolveConnectorTenant();
  if ('error' in resolved) return resolved.error;
  const body = await request.json().catch(() => ({}));
  return forwardConnectorRequest(tenantUrl(resolved.slug, 'connectors'), { method: 'POST', user: resolved.user, body });
}
