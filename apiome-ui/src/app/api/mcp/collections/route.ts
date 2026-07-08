/**
 * MCP catalog collections — proxies to apiome-rest /v1/mcp/{slug}/collections (V2-MCP-36.4).
 */

import { NextRequest, NextResponse } from 'next/server';
import {
  getAuthenticatedTenantContext,
  proxyRestGet,
  proxyRestPost,
} from '@lib/primitives-api-proxy';

export const dynamic = 'force-dynamic';

function collectionsBase(ctx: { tenantSlug: string }): string {
  return `/mcp/${encodeURIComponent(ctx.tenantSlug)}/collections`;
}

export async function GET() {
  const ctx = await getAuthenticatedTenantContext();
  if (!ctx.ok) {
    return NextResponse.json({ success: false, error: ctx.error }, { status: ctx.status });
  }
  const { data, error, status } = await proxyRestGet(ctx.user, collectionsBase(ctx));
  if (error) {
    return NextResponse.json({ success: false, error }, { status: status >= 400 ? status : 502 });
  }
  return NextResponse.json(
    {
      ...(typeof data === 'object' && data !== null ? data : {}),
      tenantSlug: ctx.tenantSlug,
    },
    { status: status || 200 },
  );
}

export async function POST(request: NextRequest) {
  const ctx = await getAuthenticatedTenantContext();
  if (!ctx.ok) {
    return NextResponse.json({ success: false, error: ctx.error }, { status: ctx.status });
  }
  const body = await request.json().catch(() => ({}));
  const { data, error, status } = await proxyRestPost(ctx.user, collectionsBase(ctx), body);
  if (error) {
    return NextResponse.json({ success: false, error }, { status: status >= 400 ? status : 502 });
  }
  return NextResponse.json(data, { status: status || 200 });
}
