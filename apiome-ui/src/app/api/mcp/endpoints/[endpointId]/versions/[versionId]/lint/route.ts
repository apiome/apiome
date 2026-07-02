/**
 * MCP endpoint version lint report — proxies to apiome-rest
 * GET /v1/mcp/{slug}/endpoints/{id}/versions/{versionId}/lint (V2-MCP-24.4 / MCAT-10.4).
 *
 * Returns a version snapshot's lint report — the deterministic 0-100 score, A-F grade, per-rule
 * and per-severity tallies, and every itemized finding — the data the "Lint & Score" tab and the
 * Overview grade summary render. The report is served from the persisted score when one exists,
 * or recomputed live by the REST API; this route stays a read-only pass-through either way.
 */

import { NextRequest, NextResponse } from 'next/server';
import { getAuthenticatedTenantContext, proxyRestGet } from '@lib/primitives-api-proxy';

export const dynamic = 'force-dynamic';

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ endpointId: string; versionId: string }> },
) {
  const { endpointId, versionId } = await params;
  if (!endpointId || !UUID_RE.test(endpointId) || !versionId || !UUID_RE.test(versionId)) {
    return NextResponse.json({ success: false, error: 'Invalid endpoint or version id' }, { status: 400 });
  }

  const ctx = await getAuthenticatedTenantContext();
  if (!ctx.ok) {
    return NextResponse.json({ success: false, error: ctx.error }, { status: ctx.status });
  }

  const { data, error, status } = await proxyRestGet(
    ctx.user,
    `/mcp/${encodeURIComponent(ctx.tenantSlug)}/endpoints/${encodeURIComponent(endpointId)}/versions/` +
      `${encodeURIComponent(versionId)}/lint`,
  );
  if (error) {
    return NextResponse.json({ success: false, error }, { status: status >= 400 ? status : 502 });
  }
  return NextResponse.json(data, { status: status || 200 });
}
