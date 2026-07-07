/**
 * MCP tenant-wide catalog analytics insight — proxies to apiome-rest
 * GET /v1/mcp/{slug}/insight/catalog (V2-MCP-32.1 / MCAT-18.1).
 *
 * Returns the tenant's whole-catalog roll-up — endpoint / published / discovered / scored counts,
 * average score, per-kind capability totals, and the composition breakdowns (category, transport,
 * protocol-version, grade, tool-count, discovery health, change leaders, top capabilities) — that the
 * **Catalog Analytics** dashboard renders. The scope comes from the authenticated session's tenant,
 * not any URL input, so this reads only the caller's own catalog. A GET stays read-only; an empty
 * catalog yields an all-empty body (a 200, never a 500).
 */

import { NextResponse } from 'next/server';
import { getAuthenticatedTenantContext, proxyRestGet } from '@lib/primitives-api-proxy';

export const dynamic = 'force-dynamic';

export async function GET() {
  const ctx = await getAuthenticatedTenantContext();
  if (!ctx.ok) {
    return NextResponse.json({ success: false, error: ctx.error }, { status: ctx.status });
  }

  const { data, error, status } = await proxyRestGet(
    ctx.user,
    `/mcp/${encodeURIComponent(ctx.tenantSlug)}/insight/catalog`,
  );
  if (error) {
    return NextResponse.json({ success: false, error }, { status: status >= 400 ? status : 502 });
  }
  return NextResponse.json(data, { status: status || 200 });
}
