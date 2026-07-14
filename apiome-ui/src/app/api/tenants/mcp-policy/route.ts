/**
 * Tenant MCP policy proxy — MTG-4.1 (#4780).
 *
 * Forwards to apiome-rest `GET`/`PUT /v1/tenants/{slug}/mcp-policy` (MTG-3.1)
 * using the session's current tenant slug. Mutations require a tenant-admin
 * user session on the REST side (MTG-3.4).
 */

import { NextRequest, NextResponse } from 'next/server';
import {
  getAuthenticatedTenantContext,
  proxyRestGet,
  proxyRestPut,
} from '@lib/primitives-api-proxy';

export const dynamic = 'force-dynamic';

function policyPath(tenantSlug: string): string {
  return `/tenants/${encodeURIComponent(tenantSlug)}/mcp-policy`;
}

export async function GET() {
  const ctx = await getAuthenticatedTenantContext();
  if (!ctx.ok) {
    return NextResponse.json({ success: false, error: ctx.error }, { status: ctx.status });
  }

  try {
    const { data, error, status } = await proxyRestGet(ctx.user, policyPath(ctx.tenantSlug));
    if (error) {
      return NextResponse.json({ success: false, error }, { status: status >= 400 ? status : 502 });
    }
    return NextResponse.json({ success: true, data });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Internal server error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}

export async function PUT(request: NextRequest) {
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
    const { data, error, status } = await proxyRestPut(ctx.user, policyPath(ctx.tenantSlug), body);
    if (error) {
      return NextResponse.json({ success: false, error }, { status: status >= 400 ? status : 502 });
    }
    return NextResponse.json({ success: true, data });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Internal server error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}
