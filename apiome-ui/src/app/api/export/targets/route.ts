import { NextRequest, NextResponse } from 'next/server';
import { getAuthenticatedTenantContext, proxyRestGet } from '@lib/primitives-api-proxy';

export const dynamic = 'force-dynamic';

/**
 * GET /api/export/targets?artifact=…&version=… — list export targets with per-source fidelity
 * (MFX-6.1, #3855).
 *
 * Proxies REST `GET /v1/export/{tenant_slug}/targets` (MFX-2.5), which enumerates every
 * registered emitter (descriptor + capability profile + options schema) with a cheap fidelity
 * badge (tier + preserved-%) computed for the requested source revision. Drives the
 * ExportDialog's target-card grid.
 */
export async function GET(request: NextRequest) {
  try {
    const ctx = await getAuthenticatedTenantContext();
    if (!ctx.ok) {
      return NextResponse.json({ success: false, error: ctx.error }, { status: ctx.status });
    }

    const artifact = request.nextUrl.searchParams.get('artifact');
    if (!artifact) {
      return NextResponse.json(
        { success: false, error: 'Missing required "artifact" query parameter' },
        { status: 400 },
      );
    }

    const params = new URLSearchParams({ artifact });
    const version = request.nextUrl.searchParams.get('version');
    if (version) params.set('version', version);

    const { data, error, status } = await proxyRestGet(
      ctx.user,
      `/export/${ctx.tenantSlug}/targets?${params.toString()}`,
    );

    if (error) {
      return NextResponse.json({ success: false, error }, { status });
    }

    return NextResponse.json({ success: true, ...(data as Record<string, unknown>) });
  } catch (error) {
    console.error('Error fetching export targets:', error);
    const message = error instanceof Error ? error.message : 'Internal server error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}
