import { NextRequest, NextResponse } from 'next/server';
import { getAuthenticatedTenantContext, proxyRestPost } from '@lib/primitives-api-proxy';

export const dynamic = 'force-dynamic';

/**
 * POST /api/export/preview — dry-run fidelity preview for one (source, target) export
 * (MFX-6.2, #3856).
 *
 * Proxies REST `POST /v1/export/{tenant_slug}/preview` (MFX-2.5), which computes the full
 * fidelity envelope — the per-construct LossinessReport, the user-facing advisory (MFX-2.4),
 * and the tier summary — **without emitting an artifact**. Drives the ExportDialog's fidelity
 * warning panel: the advisory banner, the preserved-% ring, and the expandable per-construct
 * report all render from this response.
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

    const { data, error, status } = await proxyRestPost(
      ctx.user,
      `/export/${ctx.tenantSlug}/preview`,
      body,
    );

    if (error) {
      return NextResponse.json({ success: false, error }, { status });
    }

    return NextResponse.json({ success: true, ...(data as Record<string, unknown>) });
  } catch (error) {
    console.error('Error previewing export fidelity:', error);
    const message = error instanceof Error ? error.message : 'Internal server error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}
