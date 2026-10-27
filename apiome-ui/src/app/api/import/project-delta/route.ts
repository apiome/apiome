import { NextRequest, NextResponse } from 'next/server';
import { getAuthenticatedTenantContext, proxyRestPost } from '@lib/primitives-api-proxy';

export const dynamic = 'force-dynamic';

/**
 * POST /api/import/project-delta — same-origin proxy for the Import wizard's Changes step
 * (IXH-3.7, #6321).
 *
 * Proxies REST `POST /v1/tenants/{tenant}/import/project-delta`, which compares an incoming spec
 * with the latest version of the existing Project its slug resolves to — before the import writes
 * anything. Body: `{ document, project_slug }` (optionally `project_id`, `include_documents`).
 *
 * Responds `{ success: true, delta }`; `delta` is `null` when REST answers **204** (a first-time
 * import, or one that lands in the Catalog), which is how the wizard knows to skip the step.
 */
export async function POST(request: NextRequest) {
  try {
    const ctx = await getAuthenticatedTenantContext();
    if (!ctx.ok) {
      return NextResponse.json({ success: false, error: ctx.error }, { status: ctx.status });
    }

    const body = await request.json().catch(() => null);
    if (!body || typeof body !== 'object' || !('document' in body)) {
      return NextResponse.json({ success: false, error: 'Invalid request body' }, { status: 400 });
    }

    const { data, error, status } = await proxyRestPost(
      ctx.user,
      `/tenants/${encodeURIComponent(ctx.tenantSlug)}/import/project-delta`,
      body,
    );

    // 204 carries no JSON, which the proxy reports as an error; it is the "skip" answer.
    if (status === 204) {
      return NextResponse.json({ success: true, delta: null });
    }
    if (error) {
      return NextResponse.json({ success: false, error }, { status });
    }

    return NextResponse.json({ success: true, delta: data });
  } catch (error) {
    console.error('Error comparing import with the latest version:', error);
    const message = error instanceof Error ? error.message : 'Internal server error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}
