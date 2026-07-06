import { NextRequest, NextResponse } from 'next/server';
import { getAuthenticatedTenantContext, proxyRestPost } from '@lib/primitives-api-proxy';

export const dynamic = 'force-dynamic';

/**
 * POST /api/export/verify — one-call, pre-generation Verify for one (source, target) export
 * (MFX-42.1, #4354).
 *
 * Proxies REST `POST /v1/export/{tenant_slug}/verify` (MFX-42.5), which runs the emitter to a
 * temporary buffer and returns **all three verification lenses in one dry-run** — the fidelity
 * envelope (MFX-2.5), the emitted-output validation gate (MFX-5.1/5.3), and the emitted-artifact
 * lint report (MFX-5.2) — plus an overall go/no-go verdict, **without persisting an artifact or
 * a job row**. Drives the Studio's Verify workbench: the verdict banner, the three lens tabs, and
 * the Generate gate all render from this single response.
 *
 * Unlike `/api/export/document`, the response is JSON, so it uses the shared `proxyRestPost`
 * helper and the `{ success, ... }` envelope the client hooks already expect.
 */
export async function POST(request: NextRequest) {
  try {
    const ctx = await getAuthenticatedTenantContext();
    if (!ctx.ok) {
      return NextResponse.json({ success: false, error: ctx.error }, { status: ctx.status });
    }

    const body = await request.json().catch(() => null);
    if (!body || typeof body !== 'object') {
      return NextResponse.json({ success: false, error: 'Missing request body' }, { status: 400 });
    }

    const { data, error, status } = await proxyRestPost(
      ctx.user,
      `/export/${ctx.tenantSlug}/verify`,
      body,
    );

    if (error) {
      return NextResponse.json({ success: false, error }, { status });
    }

    return NextResponse.json({ success: true, ...(data as Record<string, unknown>) });
  } catch (error) {
    console.error('Error verifying export:', error);
    const message = error instanceof Error ? error.message : 'Internal server error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}
