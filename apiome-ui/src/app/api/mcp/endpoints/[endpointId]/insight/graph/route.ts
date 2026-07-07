/**
 * MCP endpoint capability relationship graph — proxies to apiome-rest
 * GET /v1/mcp/{slug}/endpoints/{id}/insight/graph[?version_id=…] (V2-MCP-29.2 / MCAT-15.2).
 *
 * Returns the inferred node-link graph (one node per tool/resource/resource_template/prompt, plus
 * edges for prompts that name a tool, tools that reference a resource URI, and items that share a
 * schema type) for a version snapshot — the data the Insight tab's "Capability relationship graph"
 * panel renders. With no `version_id` the REST API maps the endpoint's current surface; passing one
 * maps any historical snapshot. A GET stays read-only; a never-discovered endpoint yields the
 * upstream 404 unchanged. Edge inference lives server-side (precision over recall).
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
    `/mcp/${encodeURIComponent(ctx.tenantSlug)}/endpoints/${encodeURIComponent(endpointId)}/insight/graph${query}`,
  );
  if (error) {
    return NextResponse.json({ success: false, error }, { status: status >= 400 ? status : 502 });
  }
  return NextResponse.json(data, { status: status || 200 });
}
