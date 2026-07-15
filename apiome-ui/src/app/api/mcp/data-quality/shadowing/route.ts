/**
 * MCP shadowed-name report — proxies to apiome-rest (CLX-3.4, #4858).
 * GET /v1/mcp/{slug}/data-quality/shadowing.
 *
 * Lists tool/resource/prompt names exposed by more than one *enabled* endpoint in the tenant's host
 * scope — tool shadowing (OWASP MCP09), where an agent routing by name can be steered to the wrong
 * server. Advisory, read-only pass-through.
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
    `/mcp/${encodeURIComponent(ctx.tenantSlug)}/data-quality/shadowing`,
  );
  if (error) {
    return NextResponse.json({ success: false, error }, { status: status >= 400 ? status : 502 });
  }
  return NextResponse.json(data, { status: status || 200 });
}
