/**
 * Next.js proxy for tenant MCP policy change history — MTG-5.2 (#4786).
 *
 * Forwards to apiome-rest
 * `GET /v1/tenants/{slug}/mcp-policy/history`.
 */

import { NextRequest, NextResponse } from 'next/server';
import {
  getAuthenticatedTenantContext,
  proxyRestGet,
} from '@lib/primitives-api-proxy';

export const dynamic = 'force-dynamic';

function historyPath(tenantSlug: string, search: string): string {
  const qs = search.startsWith('?') ? search : search ? `?${search}` : '';
  return `/tenants/${encodeURIComponent(tenantSlug)}/mcp-policy/history${qs}`;
}

export async function GET(request: NextRequest) {
  const ctx = await getAuthenticatedTenantContext();
  if (!ctx.ok) {
    return NextResponse.json({ success: false, error: ctx.error }, { status: ctx.status });
  }

  try {
    const { data, error, status } = await proxyRestGet(
      ctx.user,
      historyPath(ctx.tenantSlug, request.nextUrl.search),
    );
    if (error) {
      return NextResponse.json({ success: false, error }, { status: status >= 400 ? status : 502 });
    }
    return NextResponse.json({ success: true, data });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Internal server error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}
