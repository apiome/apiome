import { NextResponse } from 'next/server';
import { getAuthenticatedTenantContext } from '@lib/primitives-api-proxy';
import { createRestAuthHeaders, REST_API_BASE_URL } from '@lib/rest-auth';

export const dynamic = 'force-dynamic';

/**
 * GET /api/export/jobs/{jobId}/download — download a completed export job's artifact (MFX-46.2).
 *
 * Proxies REST `GET /v1/export/{tenant_slug}/jobs/{job_id}/download` (MFX-4.1/4.2/4.3). Like the
 * synchronous document proxy, the response body is passed through **verbatim** with its
 * `Content-Type` and `Content-Disposition` headers, because the artifact may be a single document
 * (JSON / YAML / `.proto` / `.graphql`) or an `application/zip` bundle for a multi-file target —
 * and the browser download keeps the server's filename. A job that is not completed or is a
 * dry-run is rejected by REST with 409; an expired artifact with 410 (MFX-4.3); those JSON
 * `{detail}` errors are normalized to the `{ success, error }` envelope.
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
    const response = await fetch(
      `${REST_API_BASE_URL}/export/${encodeURIComponent(ctx.tenantSlug)}/jobs/${encodeURIComponent(
        jobId,
      )}/download`,
      { method: 'GET', headers: createRestAuthHeaders(ctx.user), cache: 'no-store' },
    );

    if (!response.ok) {
      // FastAPI errors arrive as JSON {detail}; normalize to the {success, error} envelope.
      const text = await response.text();
      let detail = text || 'Download failed';
      try {
        const parsed = JSON.parse(text);
        if (typeof parsed?.detail === 'string') detail = parsed.detail;
      } catch {
        // Non-JSON error body — return it as-is.
      }
      return NextResponse.json({ success: false, error: detail }, { status: response.status });
    }

    const passthrough = new Headers();
    const contentType = response.headers.get('content-type');
    if (contentType) passthrough.set('Content-Type', contentType);
    const disposition = response.headers.get('content-disposition');
    if (disposition) passthrough.set('Content-Disposition', disposition);
    const length = response.headers.get('content-length');
    if (length) passthrough.set('Content-Length', length);

    return new NextResponse(response.body, { status: response.status, headers: passthrough });
  } catch (error) {
    console.error('Error downloading export job artifact:', error);
    const message = error instanceof Error ? error.message : 'Internal server error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}
