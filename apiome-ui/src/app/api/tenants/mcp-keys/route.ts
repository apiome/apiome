/**
 * Tenant MCP API keys list + create proxy — MTG-4.3 (#4782) / MTG-4.4 (#4783).
 *
 * Forwards to apiome-rest `GET`/`POST /v1/tenants/{slug}/mcp-keys` (MTG-3.2)
 * using the session's current tenant slug. Requires a tenant-admin user
 * session on the REST side (MTG-3.4).
 */

import { NextRequest, NextResponse } from 'next/server';
import {
  getAuthenticatedTenantContext,
  proxyRestGet,
  proxyRestPost,
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

export async function POST(request: NextRequest) {
  const ctx = await getAuthenticatedTenantContext();
  if (!ctx.ok) {
    return NextResponse.json({ success: false, error: ctx.error }, { status: ctx.status });
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ success: false, error: 'Invalid JSON body' }, { status: 400 });
  }

  try {
    const { data, error, status } = await proxyRestPost(
      ctx.user,
      keysPath(ctx.tenantSlug),
      body,
    );
    if (error) {
      return NextResponse.json({ success: false, error }, { status: status >= 400 ? status : 502 });
    }
    return NextResponse.json({ success: true, data }, { status: status || 201 });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Internal server error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}
