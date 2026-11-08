/**
 * Test one MCP capability — proxies to apiome-rest
 * POST /v1/mcp/{slug}/endpoints/{id}/test (V2-MCP-22.2; used by the Test tab, V2-MCP-22.4 / 24.5).
 *
 * Invokes a discovered tool against the live server with the endpoint's stored credential and
 * returns its content, latency, `isError` and classified error. The REST status is passed through
 * unchanged so the Test tab can tell a schema rejection (422), a destructive tool sent without
 * confirm (428) and a rate limit (429) apart.
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
    `/mcp/${encodeURIComponent(ctx.tenantSlug)}/endpoints/${encodeURIComponent(endpointId)}/test`,
    body,
  );
  if (error) {
    return NextResponse.json({ success: false, error }, { status: status >= 400 ? status : 502 });
  }
  return NextResponse.json(data, { status: status || 200 });
}
