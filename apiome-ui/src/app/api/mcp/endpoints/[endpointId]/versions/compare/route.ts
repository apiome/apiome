/**
 * MCP endpoint version compare — proxies to apiome-rest
 * GET /v1/mcp/{slug}/endpoints/{id}/versions/compare?base=&target= (V2-MCP-24.3 / MCAT-10.3).
 *
 * Computes an on-demand structured diff between any two of an endpoint's versions. The REST API
 * normalizes the pair to older→newer regardless of which id is passed as `base`, so the Versions
 * tab can submit the two ticked versions in any order. As a literal sibling of the parametrized
 * `…/versions/[versionId]` route, this segment is matched ahead of it — "compare" is never read
 * as a version id.
 */

import { NextRequest, NextResponse } from 'next/server';
import { getAuthenticatedTenantContext, proxyRestGet } from '@lib/primitives-api-proxy';

export const dynamic = 'force-dynamic';

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export async function GET(request: NextRequest, { params }: { params: Promise<{ endpointId: string }> }) {
  const { endpointId } = await params;
  if (!endpointId || !UUID_RE.test(endpointId)) {
    return NextResponse.json({ success: false, error: 'Invalid endpoint id' }, { status: 400 });
  }

  const base = request.nextUrl.searchParams.get('base') ?? '';
  const target = request.nextUrl.searchParams.get('target') ?? '';
  if (!UUID_RE.test(base) || !UUID_RE.test(target)) {
    return NextResponse.json(
      { success: false, error: 'Both base and target version ids are required' },
      { status: 400 },
    );
  }

  const ctx = await getAuthenticatedTenantContext();
  if (!ctx.ok) {
    return NextResponse.json({ success: false, error: ctx.error }, { status: ctx.status });
  }

  const query = `?base=${encodeURIComponent(base)}&target=${encodeURIComponent(target)}`;
  const { data, error, status } = await proxyRestGet(
    ctx.user,
    `/mcp/${encodeURIComponent(ctx.tenantSlug)}/endpoints/${encodeURIComponent(endpointId)}/versions/compare${query}`,
  );
  if (error) {
    return NextResponse.json({ success: false, error }, { status: status >= 400 ? status : 502 });
  }
  return NextResponse.json(data, { status: status || 200 });
}
