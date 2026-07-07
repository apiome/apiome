/**
 * MCP endpoint peer percentile & category ranking insight — proxies to apiome-rest
 * GET /v1/mcp/{slug}/endpoints/{id}/insight/percentile (V2-MCP-32.3 / MCAT-18.3).
 *
 * Returns the endpoint's percentile within its catalog category on four axes — grade, safety,
 * documentation, and latency — so the Insight tab can render "top 10% for documentation"-style peer
 * badges: a peer baseline, not an absolute grade. A GET stays read-only; a single-member category
 * still yields a coherent profile (the sole server is the category leader), an undiscovered endpoint
 * yields an all-gap profile (a 200, never a 500), and a cross-tenant endpoint passes the upstream 404
 * through unchanged.
 */

import { NextResponse } from 'next/server';
import { getAuthenticatedTenantContext, proxyRestGet } from '@lib/primitives-api-proxy';

export const dynamic = 'force-dynamic';

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ endpointId: string }> },
) {
  const { endpointId } = await params;
  if (!endpointId || !UUID_RE.test(endpointId)) {
    return NextResponse.json({ success: false, error: 'Invalid endpoint id' }, { status: 400 });
  }

  const ctx = await getAuthenticatedTenantContext();
  if (!ctx.ok) {
    return NextResponse.json({ success: false, error: ctx.error }, { status: ctx.status });
  }

  const { data, error, status } = await proxyRestGet(
    ctx.user,
    `/mcp/${encodeURIComponent(ctx.tenantSlug)}/endpoints/${encodeURIComponent(endpointId)}/insight/percentile`,
  );
  if (error) {
    return NextResponse.json({ success: false, error }, { status: status >= 400 ? status : 502 });
  }
  return NextResponse.json(data, { status: status || 200 });
}
