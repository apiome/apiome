import { NextRequest, NextResponse } from 'next/server';
import { getAuthenticatedTenantContext, proxyRestPost } from '@lib/primitives-api-proxy';

export const dynamic = 'force-dynamic';

/**
 * POST /api/import/postman/openapi — same-origin proxy for the REST Postman → OpenAPI conversion
 * (MFI-32.7, #4409): `POST /v1/import/{tenant}/postman/openapi`, which runs the collection through
 * the Postman import adapter and returns `{ source_kind, openapi, warnings }`.
 *
 * Body: `{ document: string, filename?: string, base_url?: string }`.
 * Responds `{ success: true, source_kind, openapi, warnings }`, or `{ success: false, error, code? }`
 * with the REST status (422 for a document that is not a Postman collection).
 */
export async function POST(request: NextRequest) {
  try {
    const ctx = await getAuthenticatedTenantContext();
    if (!ctx.ok) {
      return NextResponse.json({ success: false, error: ctx.error }, { status: ctx.status });
    }

    const body = await request.json().catch(() => null);
    if (!body || typeof body !== 'object' || typeof (body as { document?: unknown }).document !== 'string') {
      return NextResponse.json({ success: false, error: 'A Postman collection `document` is required' }, { status: 400 });
    }

    const { data, error, status, detail } = await proxyRestPost(
      ctx.user,
      `/import/${encodeURIComponent(ctx.tenantSlug)}/postman/openapi`,
      body
    );

    if (error) {
      const code = detail && typeof detail === 'object' ? (detail as { code?: unknown }).code : undefined;
      return NextResponse.json(
        { success: false, error, ...(typeof code === 'string' ? { code } : {}) },
        { status }
      );
    }

    return NextResponse.json({ success: true, ...(data as Record<string, unknown>) }, { status });
  } catch (error) {
    console.error('Error converting a Postman collection:', error);
    const message = error instanceof Error ? error.message : 'Internal server error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}
