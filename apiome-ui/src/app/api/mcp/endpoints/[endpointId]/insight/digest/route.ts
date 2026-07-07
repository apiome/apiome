/**
 * MCP endpoint "changed since last view" digest — proxies to apiome-rest
 * GET /v1/mcp/{slug}/endpoints/{id}/insight/digest (V2-MCP-30.5 / MCAT-16.5).
 *
 * Returns the caller's per-user digest: what changed on the endpoint's surface between the version
 * they last saw (their server-side seen-marker) and its current version, and how breaking it is —
 * `new_to_you` on a first visit, `has_changes` with the classified delta, or neither when up to
 * date. A GET stays read-only; it does NOT advance the marker (the sibling POST `/views` does), so
 * the digest reflects the pre-advance "since your last visit" state. A cross-tenant endpoint yields
 * the upstream 404 unchanged.
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
    `/mcp/${encodeURIComponent(ctx.tenantSlug)}/endpoints/${encodeURIComponent(endpointId)}/insight/digest`,
  );
  if (error) {
    return NextResponse.json({ success: false, error }, { status: status >= 400 ? status : 502 });
  }
  return NextResponse.json(data, { status: status || 200 });
}
