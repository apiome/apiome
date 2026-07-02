import { NextRequest, NextResponse } from 'next/server';
import { getAuthenticatedTenantContext, proxyRestGet } from '@lib/primitives-api-proxy';

export const dynamic = 'force-dynamic';

/** GET /api/primitives/imports — recent import provenance records (#3467 activity feed). */
export async function GET(request: NextRequest) {
  try {
    const ctx = await getAuthenticatedTenantContext();
    if (!ctx.ok) {
      return NextResponse.json({ success: false, error: ctx.error }, { status: ctx.status });
    }

    const limit = request.nextUrl.searchParams.get('limit') ?? '10';
    const path = `/primitives/${encodeURIComponent(ctx.tenantSlug)}/imports?limit=${encodeURIComponent(limit)}`;

    const { data, error, status } = await proxyRestGet(ctx.user, path);

    if (error) {
      return NextResponse.json({ success: false, error }, { status });
    }

    return NextResponse.json({ success: true, imports: data });
  } catch (error) {
    console.error('Error fetching primitive imports:', error);
    const message = error instanceof Error ? error.message : 'Internal server error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}
