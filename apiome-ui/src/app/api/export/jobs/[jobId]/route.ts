import { NextResponse } from 'next/server';
import {
  getAuthenticatedTenantContext,
  proxyRestDelete,
  proxyRestGet,
} from '@lib/primitives-api-proxy';

export const dynamic = 'force-dynamic';

/**
 * GET /api/export/jobs/{jobId} — poll one export job (MFX-46.2, #4380).
 *
 * Proxies REST `GET /v1/export/{tenant_slug}/jobs/{job_id}` (MFX-3.1), returning the job's poll
 * payload: `{ state, percent, events, progress, result, error }`. The Studio polls this until the
 * job reaches a terminal state — `completed` (with a downloadable `result`), `failed` (with a
 * structured `error`, MFX-3.4), or `canceled`.
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
      `/export/${encodeURIComponent(ctx.tenantSlug)}/jobs/${encodeURIComponent(jobId)}`,
    );

    if (error) {
      return NextResponse.json({ success: false, error }, { status });
    }

    return NextResponse.json({ success: true, ...(data as Record<string, unknown>) }, { status });
  } catch (error) {
    console.error('Error polling export job:', error);
    const message = error instanceof Error ? error.message : 'Internal server error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}

/**
 * DELETE /api/export/jobs/{jobId} — request cancellation of an export job (MFX-46.2, #4380).
 *
 * Proxies REST `DELETE /v1/export/{tenant_slug}/jobs/{job_id}` (204). The pipeline stops at its
 * next stage boundary; a job already terminal is left unchanged (a no-op).
 */
export async function DELETE(
  _request: Request,
  { params }: { params: Promise<{ jobId: string }> },
) {
  try {
    const ctx = await getAuthenticatedTenantContext();
    if (!ctx.ok) {
      return NextResponse.json({ success: false, error: ctx.error }, { status: ctx.status });
    }

    const { jobId } = await params;
    const { error, status } = await proxyRestDelete(
      ctx.user,
      `/export/${encodeURIComponent(ctx.tenantSlug)}/jobs/${encodeURIComponent(jobId)}`,
    );

    if (error) {
      return NextResponse.json({ success: false, error }, { status });
    }

    return NextResponse.json({ success: true }, { status: 200 });
  } catch (error) {
    console.error('Error canceling export job:', error);
    const message = error instanceof Error ? error.message : 'Internal server error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}
