/**
 * Record an MCP endpoint view — proxies to apiome-rest
 * POST /v1/mcp/{slug}/endpoints/{id}/views (V2-MCP-30.5 / MCAT-16.5).
 *
 * Advances the caller's per-user seen-marker to the snapshot they just saw ("the marker advances on
 * view"), so the next "changed since last view" digest reads relative to it. The body optionally
 * carries the `version_id` the client acknowledges (normally the current version, so the marker
 * records exactly what was shown); omitted, the server marks the endpoint's current version. A
 * cross-tenant endpoint (or an unknown version) yields the upstream 404 unchanged.
 */

import { NextRequest, NextResponse } from 'next/server';
import { getAuthenticatedTenantContext, proxyRestPost } from '@lib/primitives-api-proxy';

export const dynamic = 'force-dynamic';

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export async function POST(
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

  // The acknowledged version is optional; forward only a valid string so a malformed body degrades
  // to "mark the current version" server-side rather than erroring.
  const body = (await request.json().catch(() => ({}))) as { version_id?: unknown };
  const version_id = typeof body.version_id === 'string' ? body.version_id : undefined;

  const { data, error, status } = await proxyRestPost(
    ctx.user,
    `/mcp/${encodeURIComponent(ctx.tenantSlug)}/endpoints/${encodeURIComponent(endpointId)}/views`,
    version_id ? { version_id } : {},
  );
  if (error) {
    return NextResponse.json({ success: false, error }, { status: status >= 400 ? status : 502 });
  }
  return NextResponse.json(data, { status: status || 200 });
}
