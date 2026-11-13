import { NextRequest, NextResponse } from 'next/server';
import {
  getAuthenticatedTenantContext,
  proxyRestDelete,
  proxyRestPost,
} from '@lib/primitives-api-proxy';

export const dynamic = 'force-dynamic';

/** The REST path of a type's deprecation record. */
function deprecatePath(tenantSlug: string, primitiveId: string): string {
  return `/primitives/${encodeURIComponent(tenantSlug)}/${encodeURIComponent(primitiveId)}/deprecate`;
}

/**
 * POST /api/primitives/[primitiveId]/deprecate
 *
 * Deprecate a type, or change a deprecated type's details (#3482). The body carries the
 * optional `sunset_date` (`YYYY-MM-DD`), `message` and `replacement_id`. Deprecation is
 * advisory — bindings and `$ref`s keep working. System types are refused by the REST layer
 * with 403; a past sunset date or an unusable replacement with 422.
 */
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ primitiveId: string }> }
) {
  try {
    const { primitiveId } = await params;
    const ctx = await getAuthenticatedTenantContext();
    if (!ctx.ok) {
      return NextResponse.json({ success: false, error: ctx.error }, { status: ctx.status });
    }

    const body = await request.json().catch(() => ({}));

    const { data, error, status } = await proxyRestPost(
      ctx.user,
      deprecatePath(ctx.tenantSlug, primitiveId),
      body
    );

    if (error) {
      return NextResponse.json({ success: false, error }, { status });
    }

    return NextResponse.json({ success: true, primitive: data });
  } catch (error) {
    console.error('Error deprecating primitive:', error);
    const message = error instanceof Error ? error.message : 'Internal server error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}

/**
 * DELETE /api/primitives/[primitiveId]/deprecate
 *
 * Restore a deprecated type: clears its deprecation, sunset date, message and replacement
 * (#3482). Restoring a type that is not deprecated changes nothing.
 */
export async function DELETE(
  _request: NextRequest,
  { params }: { params: Promise<{ primitiveId: string }> }
) {
  try {
    const { primitiveId } = await params;
    const ctx = await getAuthenticatedTenantContext();
    if (!ctx.ok) {
      return NextResponse.json({ success: false, error: ctx.error }, { status: ctx.status });
    }

    const { data, error, status } = await proxyRestDelete(
      ctx.user,
      deprecatePath(ctx.tenantSlug, primitiveId)
    );

    if (error) {
      return NextResponse.json({ success: false, error }, { status });
    }

    return NextResponse.json({ success: true, primitive: data });
  } catch (error) {
    console.error('Error restoring primitive:', error);
    const message = error instanceof Error ? error.message : 'Internal server error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}
