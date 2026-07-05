import { NextRequest, NextResponse } from 'next/server';
import { getAuthenticatedTenantContext } from '@lib/primitives-api-proxy';
import { createRestAuthHeaders, REST_API_BASE_URL } from '@lib/rest-auth';

export const dynamic = 'force-dynamic';

/**
 * POST /api/export/document — emit the export document for one target (MFX-6.1, #3855).
 *
 * Proxies REST `POST /v1/export/{tenant_slug}/document` (MFX-11.5), which emits the source
 * artifact/version to the chosen target and returns the document itself. Unlike the JSON proxy
 * helpers, the response body is passed through **verbatim** with its `Content-Type` and
 * `Content-Disposition` headers, because the emitted artifact may be JSON, YAML, or plain text
 * (e.g. a `.proto` or `.graphql` file) and the browser download keeps the server's filename.
 */
export async function POST(request: NextRequest) {
  try {
    const ctx = await getAuthenticatedTenantContext();
    if (!ctx.ok) {
      return NextResponse.json({ success: false, error: ctx.error }, { status: ctx.status });
    }

    const body = await request.json().catch(() => null);
    if (!body || typeof body !== 'object') {
      return NextResponse.json(
        { success: false, error: 'Missing request body' },
        { status: 400 },
      );
    }

    // Forward the caller's Accept header so YAML serialization (Accept: application/yaml)
    // negotiates end to end.
    const headers: Record<string, string> = createRestAuthHeaders(ctx.user);
    const accept = request.headers.get('accept');
    if (accept) headers.Accept = accept;

    const response = await fetch(`${REST_API_BASE_URL}/export/${ctx.tenantSlug}/document`, {
      method: 'POST',
      headers,
      cache: 'no-store',
      body: JSON.stringify(body),
    });

    if (!response.ok) {
      // FastAPI errors arrive as JSON {detail}; normalize to the {success, error} envelope.
      const text = await response.text();
      let detail = text || 'Export failed';
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

    return new NextResponse(response.body, { status: response.status, headers: passthrough });
  } catch (error) {
    console.error('Error emitting export document:', error);
    const message = error instanceof Error ? error.message : 'Internal server error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}
