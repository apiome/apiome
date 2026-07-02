import { NextResponse } from 'next/server';
import { getAuthenticatedTenantContext, proxyRestGet } from '@lib/primitives-api-proxy';

export const dynamic = 'force-dynamic';

/**
 * GET /api/catalog/import/{jobId} — poll a catalog store-raw import job (MFI-23.7).
 *
 * Proxies REST `GET /v1/tenants/{tenant}/imports/{job_id}`, returning the job's poll payload
 * (state, percent, events, summary, and — once persisted — the produced project/version ids in
 * `result`). The client polls this until the job reaches a terminal state.
 */
export async function GET(
  _request: Request,
  { params }: { params: Promise<{ jobId: string }> },
) {
  try {
    const ctx = await getAuthenticatedTenantContext();
    if (!ctx.ok) {
      return NextResponse.json({ success: false, error: ctx.error }, { status: ctx.status });
    }

    const { jobId } = await params;
    const { data, error, status } = await proxyRestGet(
      ctx.user,
      `/tenants/${encodeURIComponent(ctx.tenantSlug)}/imports/${encodeURIComponent(jobId)}`,
    );

    if (error) {
      return NextResponse.json({ success: false, error }, { status });
    }

    return NextResponse.json({ success: true, ...(data as Record<string, unknown>) }, { status });
  } catch (error) {
    console.error('Error polling catalog import:', error);
    const message = error instanceof Error ? error.message : 'Internal server error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}
