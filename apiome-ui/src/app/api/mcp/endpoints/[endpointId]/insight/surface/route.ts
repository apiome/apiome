/**
 * MCP endpoint capability-surface insight — proxies to apiome-rest
 * GET /v1/mcp/{slug}/endpoints/{id}/insight/surface[?version_id=…] (V2-MCP-28.2 / MCAT-14.2).
 *
 * Returns the deterministic capability-surface metrics roll-up (per-kind counts, per-tool schema
 * complexity, annotation and documentation coverage) for a version snapshot — the data the Insight
 * tab (V2-MCP-28.4) lazy-loads and its 15.x panels render. With no `version_id` the REST API
 * summarizes the endpoint's current surface; passing one views any historical snapshot. A GET stays
 * read-only either way; a never-discovered endpoint yields the upstream 404 unchanged.
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

  // Optional snapshot selector — validated to a UUID so a malformed query never reaches upstream.
  const versionId = request.nextUrl.searchParams.get('version_id');
  if (versionId && !UUID_RE.test(versionId)) {
    return NextResponse.json({ success: false, error: 'Invalid version id' }, { status: 400 });
  }

  const ctx = await getAuthenticatedTenantContext();
  if (!ctx.ok) {
    return NextResponse.json({ success: false, error: ctx.error }, { status: ctx.status });
  }

  const query = versionId ? `?version_id=${encodeURIComponent(versionId)}` : '';
  const { data, error, status } = await proxyRestGet(
    ctx.user,
    `/mcp/${encodeURIComponent(ctx.tenantSlug)}/endpoints/${encodeURIComponent(endpointId)}/insight/surface${query}`,
  );
  if (error) {
    return NextResponse.json({ success: false, error }, { status: status >= 400 ? status : 502 });
  }
  return NextResponse.json(data, { status: status || 200 });
}
