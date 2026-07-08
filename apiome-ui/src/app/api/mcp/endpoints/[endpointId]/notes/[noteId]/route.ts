/**
 * One cataloger note on an MCP endpoint — GET/PATCH/DELETE (V2-MCP-36.3 / MCAT-22.3, #4666).
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

function notePath(
  ctx: { tenantSlug: string },
  endpointId: string,
  noteId: string,
): string {
  return (
    `/mcp/${encodeURIComponent(ctx.tenantSlug)}` +
    `/endpoints/${encodeURIComponent(endpointId)}/notes/${encodeURIComponent(noteId)}`
  );
}

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ endpointId: string; noteId: string }> },
) {
  const { endpointId, noteId } = await params;
  if (!endpointId || !UUID_RE.test(endpointId) || !noteId || !UUID_RE.test(noteId)) {
    return NextResponse.json({ success: false, error: 'Invalid id' }, { status: 400 });
  }
  const ctx = await getAuthenticatedTenantContext();
  if (!ctx.ok) {
    return NextResponse.json({ success: false, error: ctx.error }, { status: ctx.status });
  }
  const { data, error, status } = await proxyRestGet(
    ctx.user,
    notePath(ctx, endpointId, noteId),
  );
  if (error) {
    return NextResponse.json({ success: false, error }, { status: status >= 400 ? status : 502 });
  }
  return NextResponse.json(data, { status: status || 200 });
}

export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ endpointId: string; noteId: string }> },
) {
  const { endpointId, noteId } = await params;
  if (!endpointId || !UUID_RE.test(endpointId) || !noteId || !UUID_RE.test(noteId)) {
    return NextResponse.json({ success: false, error: 'Invalid id' }, { status: 400 });
  }
  const ctx = await getAuthenticatedTenantContext();
  if (!ctx.ok) {
    return NextResponse.json({ success: false, error: ctx.error }, { status: ctx.status });
  }
  const body = await request.json().catch(() => ({}));
  const { data, error, status } = await proxyRestPatch(
    ctx.user,
    notePath(ctx, endpointId, noteId),
    body,
  );
  if (error) {
    return NextResponse.json({ success: false, error }, { status: status >= 400 ? status : 502 });
  }
  return NextResponse.json(data, { status: status || 200 });
}

export async function DELETE(
  _request: NextRequest,
  { params }: { params: Promise<{ endpointId: string; noteId: string }> },
) {
  const { endpointId, noteId } = await params;
  if (!endpointId || !UUID_RE.test(endpointId) || !noteId || !UUID_RE.test(noteId)) {
    return NextResponse.json({ success: false, error: 'Invalid id' }, { status: 400 });
  }
  const ctx = await getAuthenticatedTenantContext();
  if (!ctx.ok) {
    return NextResponse.json({ success: false, error: ctx.error }, { status: ctx.status });
  }
  const { data, error, status } = await proxyRestDelete(
    ctx.user,
    notePath(ctx, endpointId, noteId),
  );
  if (error) {
    return NextResponse.json({ success: false, error }, { status: status >= 400 ? status : 502 });
  }
  return NextResponse.json(data, { status: status || 200 });
}
