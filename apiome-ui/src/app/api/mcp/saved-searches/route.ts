/**
 * Saved catalog searches — proxies to apiome-rest /v1/mcp/{slug}/saved-searches (V2-MCP-35.3).
 */

import { NextRequest, NextResponse } from 'next/server';
import {
  getAuthenticatedTenantContext,
  proxyRestGet,
  proxyRestPost,
} from '@lib/primitives-api-proxy';

export const dynamic = 'force-dynamic';

function savedSearchBase(ctx: { tenantSlug: string }): string {
  return `/mcp/${encodeURIComponent(ctx.tenantSlug)}/saved-searches`;
}

export async function GET() {
  const ctx = await getAuthenticatedTenantContext();
  if (!ctx.ok) {
    return NextResponse.json({ success: false, error: ctx.error }, { status: ctx.status });
  }
  const { data, error, status } = await proxyRestGet(ctx.user, savedSearchBase(ctx));
  if (error) {
    return NextResponse.json({ success: false, error }, { status: status >= 400 ? status : 502 });
  }
  return NextResponse.json(data, { status: status || 200 });
}

export async function POST(request: NextRequest) {
  const ctx = await getAuthenticatedTenantContext();
  if (!ctx.ok) {
    return NextResponse.json({ success: false, error: ctx.error }, { status: ctx.status });
  }
  const body = await request.json().catch(() => ({}));
  const { data, error, status } = await proxyRestPost(ctx.user, savedSearchBase(ctx), body);
  if (error) {
    return NextResponse.json({ success: false, error }, { status: status >= 400 ? status : 502 });
  }
  return NextResponse.json(data, { status: status || 200 });
}
