/**
 * One saved catalog search — GET/DELETE by id (V2-MCP-35.3).
 */

import { NextRequest, NextResponse } from 'next/server';
import {
  getAuthenticatedTenantContext,
  proxyRestDelete,
  proxyRestGet,
  proxyRestPatch,
} from '@lib/primitives-api-proxy';

export const dynamic = 'force-dynamic';

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function savedSearchPath(ctx: { tenantSlug: string }, searchId: string): string {
  return `/mcp/${encodeURIComponent(ctx.tenantSlug)}/saved-searches/${encodeURIComponent(searchId)}`;
}

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ searchId: string }> },
) {
  const { searchId } = await params;
  if (!searchId || !UUID_RE.test(searchId)) {
    return NextResponse.json({ success: false, error: 'Invalid saved search id' }, { status: 400 });
  }
  const ctx = await getAuthenticatedTenantContext();
  if (!ctx.ok) {
    return NextResponse.json({ success: false, error: ctx.error }, { status: ctx.status });
  }
  const { data, error, status } = await proxyRestGet(ctx.user, savedSearchPath(ctx, searchId));
  if (error) {
    return NextResponse.json({ success: false, error }, { status: status >= 400 ? status : 502 });
  }
  return NextResponse.json(data, { status: status || 200 });
}

export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ searchId: string }> },
) {
  const { searchId } = await params;
  if (!searchId || !UUID_RE.test(searchId)) {
    return NextResponse.json({ success: false, error: 'Invalid saved search id' }, { status: 400 });
  }
  const ctx = await getAuthenticatedTenantContext();
  if (!ctx.ok) {
    return NextResponse.json({ success: false, error: ctx.error }, { status: ctx.status });
  }
  const body = await request.json().catch(() => ({}));
  const { data, error, status } = await proxyRestPatch(
    ctx.user,
    savedSearchPath(ctx, searchId),
    body,
  );
  if (error) {
    return NextResponse.json({ success: false, error }, { status: status >= 400 ? status : 502 });
  }
  return NextResponse.json(data, { status: status || 200 });
}

export async function DELETE(
  _request: NextRequest,
  { params }: { params: Promise<{ searchId: string }> },
) {
  const { searchId } = await params;
  if (!searchId || !UUID_RE.test(searchId)) {
    return NextResponse.json({ success: false, error: 'Invalid saved search id' }, { status: 400 });
  }
  const ctx = await getAuthenticatedTenantContext();
  if (!ctx.ok) {
    return NextResponse.json({ success: false, error: ctx.error }, { status: ctx.status });
  }
  const { data, error, status } = await proxyRestDelete(ctx.user, savedSearchPath(ctx, searchId));
  if (error) {
    return NextResponse.json({ success: false, error }, { status: status >= 400 ? status : 502 });
  }
  return NextResponse.json(data ?? { success: true }, { status: status || 200 });
}
