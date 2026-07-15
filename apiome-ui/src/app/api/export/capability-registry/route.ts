import { NextResponse } from 'next/server';
import { getAuthenticatedTenantContext, proxyRestGet } from '@lib/primitives-api-proxy';

export const dynamic = 'force-dynamic';

/**
 * GET /api/export/capability-registry — the destination capability & documentation registry
 * (EFP-1.2, #4811).
 *
 * Proxies REST `GET /v1/export/{tenant_slug}/capability-registry`, which returns the versioned
 * registry: one reviewed capability entry per registered export destination (label,
 * availability, and host-allowlisted documentation with a safe fallback) plus the reviewed
 * explanation for every projection reason code. Static reference data — the same for every
 * source — that lets the export UI render honest loss reasons and authoritative documentation
 * links from reviewed data instead of hard-coding URLs in components.
 */
export async function GET() {
  try {
    const ctx = await getAuthenticatedTenantContext();
    if (!ctx.ok) {
      return NextResponse.json({ success: false, error: ctx.error }, { status: ctx.status });
    }

    const { data, error, status } = await proxyRestGet(
      ctx.user,
      `/export/${ctx.tenantSlug}/capability-registry`,
    );

    if (error) {
      return NextResponse.json({ success: false, error }, { status });
    }

    return NextResponse.json({ success: true, ...(data as Record<string, unknown>) });
  } catch (error) {
    console.error('Error fetching export capability registry:', error);
    const message = error instanceof Error ? error.message : 'Internal server error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}
