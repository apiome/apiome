/**
 * MCP endpoint uptime — proxies to apiome-rest
 * GET /v1/mcp/{slug}/endpoints/{id}/uptime (V2-MCP-27.3 / MCAT-13.3).
 *
 * Returns the endpoint's reachability summary over the last `window_hours` (default 24) — status
 * (up / degraded / down / unknown), uptime %, p50 / p95 latency — and its most recent probes, which
 * the endpoint page's health badge renders. `window_hours` and `limit` are forwarded when given. A
 * GET stays read-only; an endpoint never probed yields `status: "unknown"` (a 200), and a
 * cross-tenant endpoint the upstream 404 unchanged.
 */

import { NextResponse } from 'next/server';
import { getAuthenticatedTenantContext, proxyRestGet } from '@lib/primitives-api-proxy';

export const dynamic = 'force-dynamic';

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

/** Query parameters forwarded upstream; each must be a positive integer (the upstream bounds-checks). */
const FORWARDED_PARAMS = ['window_hours', 'limit'] as const;

export async function GET(
  request: Request,
  { params }: { params: Promise<{ endpointId: string }> },
) {
  const { endpointId } = await params;
  if (!endpointId || !UUID_RE.test(endpointId)) {
    return NextResponse.json({ success: false, error: 'Invalid endpoint id' }, { status: 400 });
  }

  const incoming = new URL(request.url).searchParams;
  const query = new URLSearchParams();
  for (const name of FORWARDED_PARAMS) {
    const value = incoming.get(name);
    if (value === null) continue;
    if (!/^\d+$/.test(value)) {
      return NextResponse.json({ success: false, error: `Invalid ${name}` }, { status: 400 });
    }
    query.set(name, value);
  }

  const ctx = await getAuthenticatedTenantContext();
  if (!ctx.ok) {
    return NextResponse.json({ success: false, error: ctx.error }, { status: ctx.status });
  }

  const suffix = query.toString() ? `?${query.toString()}` : '';
  const { data, error, status } = await proxyRestGet(
    ctx.user,
    `/mcp/${encodeURIComponent(ctx.tenantSlug)}/endpoints/${encodeURIComponent(endpointId)}/uptime${suffix}`,
  );
  if (error) {
    return NextResponse.json({ success: false, error }, { status: status >= 400 ? status : 502 });
  }
  return NextResponse.json(data, { status: status || 200 });
}
