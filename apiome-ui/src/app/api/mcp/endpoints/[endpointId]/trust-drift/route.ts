/**
 * MCP endpoint trust-drift report — proxies to apiome-rest (CLX-3.4, #4858).
 * GET /v1/mcp/{slug}/endpoints/{id}/trust-drift.
 *
 * Diffs the endpoint's current snapshot against its operator-approved trust baseline and classifies
 * every material surface/source change (normal change / quality regression / security regression /
 * coverage loss), each carrying an old→new evidence reference, plus the gate over the baseline's
 * configured risk deltas. Read-only pass-through; the `?notify` flag is forwarded verbatim.
 */

import { NextRequest, NextResponse } from 'next/server';
import { getAuthenticatedTenantContext, proxyRestGet } from '@lib/primitives-api-proxy';

export const dynamic = 'force-dynamic';

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export async function GET(
  request: NextRequest,
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

  const notify = request.nextUrl.searchParams.get('notify');
  const query = notify === 'true' ? '?notify=true' : '';

  const { data, error, status } = await proxyRestGet(
    ctx.user,
    `/mcp/${encodeURIComponent(ctx.tenantSlug)}/endpoints/${encodeURIComponent(endpointId)}/trust-drift${query}`,
  );
  if (error) {
    return NextResponse.json({ success: false, error }, { status: status >= 400 ? status : 502 });
  }
  return NextResponse.json(data, { status: status || 200 });
}
