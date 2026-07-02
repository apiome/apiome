/**
 * Poll MCP discovery job — proxies to apiome-rest
 * GET /v1/mcp/{slug}/endpoints/{id}/discover/{jobId} (V2-MCP-24.1).
 *
 * Returns one discovery job's current state/result so the Import dialog can show live status and,
 * on completion, resolve the catalog version the run produced.
 */

import { NextRequest, NextResponse } from 'next/server';
import { getAuthenticatedTenantContext, proxyRestGet } from '@lib/primitives-api-proxy';

export const dynamic = 'force-dynamic';

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ endpointId: string; jobId: string }> },
) {
  const { endpointId, jobId } = await params;
  if (!endpointId || !UUID_RE.test(endpointId)) {
    return NextResponse.json({ success: false, error: 'Invalid endpoint id' }, { status: 400 });
  }
  if (!jobId || !UUID_RE.test(jobId)) {
    return NextResponse.json({ success: false, error: 'Invalid job id' }, { status: 400 });
  }

  const ctx = await getAuthenticatedTenantContext();
  if (!ctx.ok) {
    return NextResponse.json({ success: false, error: ctx.error }, { status: ctx.status });
  }

  const { data, error, status } = await proxyRestGet(
    ctx.user,
    `/mcp/${encodeURIComponent(ctx.tenantSlug)}/endpoints/${encodeURIComponent(endpointId)}/discover/${encodeURIComponent(jobId)}`,
  );
  if (error) {
    return NextResponse.json({ success: false, error }, { status: status >= 400 ? status : 502 });
  }
  return NextResponse.json(data, { status: status || 200 });
}
