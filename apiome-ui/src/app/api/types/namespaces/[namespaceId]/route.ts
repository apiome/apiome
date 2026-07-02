import { NextRequest, NextResponse } from 'next/server';
import { getAuthenticatedTenantContext, proxyRestPut } from '@lib/primitives-api-proxy';

export const dynamic = 'force-dynamic';

/**
 * PUT /api/types/namespaces/[namespaceId]
 *
 * Update a tenant namespace's base URI, version root, description, or default flag (Namespaces
 * UI #3471 / API #3451). The namespace path itself is immutable; system-core namespaces are
 * read-only and the REST layer rejects them with 403.
 */
export async function PUT(
  request: NextRequest,
  { params }: { params: Promise<{ namespaceId: string }> }
) {
  try {
    const { namespaceId } = await params;
    const ctx = await getAuthenticatedTenantContext();
    if (!ctx.ok) {
      return NextResponse.json({ success: false, error: ctx.error }, { status: ctx.status });
    }

    const body = await request.json();

    const { data, error, status } = await proxyRestPut(
      ctx.user,
      `/types/${encodeURIComponent(ctx.tenantSlug)}/namespaces/${encodeURIComponent(namespaceId)}`,
      body
    );

    if (error) {
      return NextResponse.json({ success: false, error }, { status });
    }

    return NextResponse.json({ success: true, namespace: data });
  } catch (error) {
    console.error('Error updating type namespace:', error);
    const message = error instanceof Error ? error.message : 'Internal server error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}
