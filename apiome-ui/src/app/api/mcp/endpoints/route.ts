/**
 * Create MCP endpoint — proxies to apiome-rest POST /v1/mcp/{slug}/endpoints (V2-MCP-24.1).
 *
 * Backs the "MCP Server" import source: registers a new catalog endpoint for the caller's tenant
 * from the URL + transport collected in the Import dialog. The discovery run is kicked off
 * separately via the `/discover` route once the endpoint (and any credential) exists.
 */

import { NextRequest, NextResponse } from 'next/server';
import { getAuthenticatedTenantContext, proxyRestPost } from '@lib/primitives-api-proxy';

export const dynamic = 'force-dynamic';

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

  const { data, error, status } = await proxyRestPost(
    ctx.user,
    `/mcp/${encodeURIComponent(ctx.tenantSlug)}/endpoints`,
    body,
  );
  if (error) {
    return NextResponse.json({ success: false, error }, { status: status >= 400 ? status : 502 });
  }
  return NextResponse.json(data, { status: status || 201 });
}
