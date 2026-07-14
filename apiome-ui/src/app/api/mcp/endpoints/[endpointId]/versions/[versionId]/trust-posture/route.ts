/**
 * MCP endpoint version trust-posture report — proxies to apiome-rest (CLX-3.2, #4856).
 * GET /v1/mcp/{slug}/endpoints/{id}/versions/{versionId}/trust-posture.
 *
 * Returns a snapshot's source / supply-chain / trust-posture report: the OWASP-mapped findings,
 * each carrying its evidence origin and its exploitability ("signal", never "proven" without a
 * dynamic probe), the skipped-rule coverage gaps, and the gate decision. Read-only pass-through;
 * the `?profile` / `?failOn` / `?minScore` / `?requireFullCoverage` query is forwarded verbatim.
 */

import { NextRequest, NextResponse } from 'next/server';
import { getAuthenticatedTenantContext, proxyRestGet } from '@lib/primitives-api-proxy';

export const dynamic = 'force-dynamic';

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ endpointId: string; versionId: string }> },
) {
  const { endpointId, versionId } = await params;
  if (!endpointId || !UUID_RE.test(endpointId) || !versionId || !UUID_RE.test(versionId)) {
    return NextResponse.json({ success: false, error: 'Invalid endpoint or version id' }, { status: 400 });
  }

  const ctx = await getAuthenticatedTenantContext();
  if (!ctx.ok) {
    return NextResponse.json({ success: false, error: ctx.error }, { status: ctx.status });
  }

  // Forward only the recognized query params, so the panel controls the scan without this route
  // needing to know the full option set.
  const incoming = request.nextUrl.searchParams;
  const forwarded = new URLSearchParams();
  for (const key of ['profile', 'failOn', 'minScore', 'requireFullCoverage', 'format']) {
    const value = incoming.get(key);
    if (value != null) forwarded.set(key, value);
  }
  const query = forwarded.toString();

  const { data, error, status } = await proxyRestGet(
    ctx.user,
    `/mcp/${encodeURIComponent(ctx.tenantSlug)}/endpoints/${encodeURIComponent(endpointId)}/versions/` +
      `${encodeURIComponent(versionId)}/trust-posture${query ? `?${query}` : ''}`,
  );
  if (error) {
    return NextResponse.json({ success: false, error }, { status: status >= 400 ? status : 502 });
  }
  return NextResponse.json(data, { status: status || 200 });
}
