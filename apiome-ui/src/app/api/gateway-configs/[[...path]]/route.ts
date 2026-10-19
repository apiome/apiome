/**
 * The gateway configs proxy — CDG-5.3 (#5981): `GET /api/gateway-configs[/{slug}]` →
 * `/v1/tenants/{t}/gateway-configs[/{slug}]`. Read-only; `imports:view` is apiome-rest's.
 */

import { NextRequest, NextResponse } from 'next/server';
import { forwardConnectorRequest, resolveConnectorTenant, tenantUrl } from '@lib/connectors-proxy';
import { gatewayConfigProxyPath } from '@lib/gateway-configs';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest, context: { params: Promise<{ path?: string[] }> }) {
  const path = gatewayConfigProxyPath((await context.params).path ?? []);
  if (path === null) return NextResponse.json({ success: false, error: 'Unknown path.' }, { status: 404 });
  const resolved = await resolveConnectorTenant();
  if ('error' in resolved) return resolved.error;
  const connector = request.nextUrl.searchParams.get('connector');
  const query = path === 'gateway-configs' && connector && /^[0-9a-fA-F-]{36}$/.test(connector) ? `?connector=${connector}` : '';
  return forwardConnectorRequest(tenantUrl(resolved.slug, `${path}${query}`), {
    method: 'GET',
    user: resolved.user,
    unavailable: 'The gateway configs are unavailable (apiome-rest not reachable). Try again shortly.',
  });
}
