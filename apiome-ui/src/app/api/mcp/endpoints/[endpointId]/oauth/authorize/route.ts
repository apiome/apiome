/**
 * Start an OAuth connection to an MCP endpoint — proxies to apiome-rest
 * POST /v1/mcp/{slug}/endpoints/{id}/oauth/authorize (V2-MCP-20.4 / MCAT-6.4, #3680).
 *
 * Returns the authorization URL (PKCE S256, RFC 8707 resource, sealed state) the browser is sent
 * to. Body: `{ redirect_uri, client_id?, client_secret?, scopes? }`.
 */

import { NextRequest, NextResponse } from 'next/server';
import { getAuthenticatedTenantContext, proxyRestPost } from '@lib/primitives-api-proxy';

export const dynamic = 'force-dynamic';

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export async function POST(request: NextRequest, { params }: { params: Promise<{ endpointId: string }> }) {
  const { endpointId } = await params;
  if (!endpointId || !UUID_RE.test(endpointId)) {
    return NextResponse.json({ success: false, error: 'Invalid endpoint id' }, { status: 400 });
  }

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
    `/mcp/${encodeURIComponent(ctx.tenantSlug)}/endpoints/${encodeURIComponent(endpointId)}/oauth/authorize`,
    body,
  );
  if (error) {
    return NextResponse.json({ success: false, error }, { status: status >= 400 ? status : 502 });
  }
  return NextResponse.json(data, { status: status || 200 });
}
