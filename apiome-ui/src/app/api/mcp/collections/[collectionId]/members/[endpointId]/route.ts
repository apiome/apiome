/**
 * Remove one endpoint from an MCP collection (V2-MCP-36.4 / MCAT-22.4, #4667).
 */

import { NextRequest, NextResponse } from 'next/server';
import { getAuthenticatedTenantContext, proxyRestDelete } from '@lib/primitives-api-proxy';

export const dynamic = 'force-dynamic';

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function memberPath(
  ctx: { tenantSlug: string },
  collectionId: string,
  endpointId: string,
): string {
  return (
    `/mcp/${encodeURIComponent(ctx.tenantSlug)}` +
    `/collections/${encodeURIComponent(collectionId)}` +
    `/members/${encodeURIComponent(endpointId)}`
  );
}

export async function DELETE(
  _request: NextRequest,
  { params }: { params: Promise<{ collectionId: string; endpointId: string }> },
) {
  const { collectionId, endpointId } = await params;
  if (!collectionId || !UUID_RE.test(collectionId) || !endpointId || !UUID_RE.test(endpointId)) {
    return NextResponse.json({ success: false, error: 'Invalid collection or endpoint id' }, { status: 400 });
  }
  const ctx = await getAuthenticatedTenantContext();
  if (!ctx.ok) {
    return NextResponse.json({ success: false, error: ctx.error }, { status: ctx.status });
  }
  const { data, error, status } = await proxyRestDelete(
    ctx.user,
    memberPath(ctx, collectionId, endpointId),
  );
  if (error) {
    return NextResponse.json({ success: false, error }, { status: status >= 400 ? status : 502 });
  }
  return NextResponse.json(data ?? { success: true }, { status: status || 200 });
}
