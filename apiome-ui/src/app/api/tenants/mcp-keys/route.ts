/**
 * Tenant MCP API keys list proxy — MTG-4.3 (#4782).
 *
 * Forwards to apiome-rest `GET /v1/tenants/{slug}/mcp-keys` (MTG-3.2)
 * using the session's current tenant slug. Requires a tenant-admin user
 * session on the REST side (MTG-3.4).
 */

import { NextResponse } from 'next/server';
import {
  getAuthenticatedTenantContext,
  proxyRestGet,
} from '@lib/primitives-api-proxy';

export const dynamic = 'force-dynamic';

function keysPath(tenantSlug: string): string {
  return `/tenants/${encodeURIComponent(tenantSlug)}/mcp-keys`;
}

export async function GET() {
  const ctx = await getAuthenticatedTenantContext();
  if (!ctx.ok) {
    return NextResponse.json({ success: false, error: ctx.error }, { status: ctx.status });
  }

  try {
    const { data, error, status } = await proxyRestGet(ctx.user, keysPath(ctx.tenantSlug));
    if (error) {
      return NextResponse.json({ success: false, error }, { status: status >= 400 ? status : 502 });
    }
    return NextResponse.json({ success: true, data });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Internal server error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}
