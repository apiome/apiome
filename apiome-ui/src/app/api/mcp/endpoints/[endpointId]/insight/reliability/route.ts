/**
 * MCP endpoint reliability & discovery-health insight — proxies to apiome-rest
 * GET /v1/mcp/{slug}/endpoints/{id}/insight/reliability (V2-MCP-31.1 / MCAT-17.1).
 *
 * Returns the endpoint's discovery + test-invocation reliability aggregates plus the discovery
 * `health` block the Insight tab's "Discovery health timeline" renders: the recent per-job outcome
 * events (ok / unreachable / auth_error / …), a windowed availability percentage, and the endpoint's
 * quarantine / backoff state. A GET stays read-only; a never-discovered endpoint yields an empty
 * timeline (a 200, never a 500), and a cross-tenant endpoint the upstream 404 unchanged.
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
    `/mcp/${encodeURIComponent(ctx.tenantSlug)}/endpoints/${encodeURIComponent(endpointId)}/insight/reliability`,
  );
  if (error) {
    return NextResponse.json({ success: false, error }, { status: status >= 400 ? status : 502 });
  }
  return NextResponse.json(data, { status: status || 200 });
}
