/**
 * MCP endpoint report-card export — proxies to apiome-rest
 * GET /v1/mcp/{slug}/endpoints/{id}/report?format=markdown|html[&version_id=…] (V2-MCP-33.1 / MCAT-19.1).
 *
 * Serializes the in-app Insight assessment (identity, grade + score breakdown, capability surface,
 * safety posture, documentation coverage, trust radar, change-since-previous) into a shareable
 * Markdown or HTML document. Unlike the JSON insight proxies, the upstream body is a rendered file,
 * so it is passed through **verbatim** with its `Content-Type` and `Content-Disposition` (the
 * attachment filename the server chose). "PDF" is the browser's print-to-PDF of the HTML variant,
 * whose print stylesheet is embedded — so this route only ever fetches `markdown` / `html`.
 */

import { NextRequest, NextResponse } from 'next/server';
import { getAuthenticatedTenantContext } from '@lib/primitives-api-proxy';
import { createRestAuthHeaders, REST_API_BASE_URL } from '@lib/rest-auth';

export const dynamic = 'force-dynamic';

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const ALLOWED_FORMATS = new Set(['markdown', 'md', 'html']);

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ endpointId: string }> },
) {
  const { endpointId } = await params;
  if (!endpointId || !UUID_RE.test(endpointId)) {
    return NextResponse.json({ success: false, error: 'Invalid endpoint id' }, { status: 400 });
  }

  // Validate the format up front so a bad value never reaches upstream (which would 400 anyway).
  const format = (request.nextUrl.searchParams.get('format') || 'markdown').toLowerCase();
  if (!ALLOWED_FORMATS.has(format)) {
    return NextResponse.json(
      { success: false, error: "Unsupported format; use 'markdown' or 'html'" },
      { status: 400 },
    );
  }

  // Optional snapshot selector — validated to a UUID so a malformed query never reaches upstream.
  const versionId = request.nextUrl.searchParams.get('version_id');
  if (versionId && !UUID_RE.test(versionId)) {
    return NextResponse.json({ success: false, error: 'Invalid version id' }, { status: 400 });
  }

  const includeCatalogerNotes =
    request.nextUrl.searchParams.get('include_cataloger_notes') === 'true';

  const ctx = await getAuthenticatedTenantContext();
  if (!ctx.ok) {
    return NextResponse.json({ success: false, error: ctx.error }, { status: ctx.status });
  }

  const query = new URLSearchParams({ format });
  if (versionId) query.set('version_id', versionId);
  if (includeCatalogerNotes) query.set('include_cataloger_notes', 'true');
  const url =
    `${REST_API_BASE_URL}/mcp/${encodeURIComponent(ctx.tenantSlug)}` +
    `/endpoints/${encodeURIComponent(endpointId)}/report?${query.toString()}`;

  const response = await fetch(url, {
    method: 'GET',
    headers: createRestAuthHeaders(ctx.user),
    cache: 'no-store',
  });

  if (!response.ok) {
    // FastAPI errors arrive as JSON {detail}; normalize to the {success, error} envelope.
    const text = await response.text();
    let detail = text || 'Report export failed';
    try {
      const parsed = JSON.parse(text);
      if (typeof parsed?.detail === 'string') detail = parsed.detail;
    } catch {
      // Non-JSON error body — return it as-is.
    }
    return NextResponse.json({ success: false, error: detail }, { status: response.status });
  }

  // Pass the rendered document through verbatim, keeping the server's content type + filename.
  const passthrough = new Headers();
  const contentType = response.headers.get('content-type');
  if (contentType) passthrough.set('Content-Type', contentType);
  const disposition = response.headers.get('content-disposition');
  if (disposition) passthrough.set('Content-Disposition', disposition);

  return new NextResponse(response.body, { status: response.status, headers: passthrough });
}
