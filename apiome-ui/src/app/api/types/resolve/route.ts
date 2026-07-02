import { NextResponse } from 'next/server';
import { getAuthenticatedTenantContext, proxyRestPost } from '@lib/primitives-api-proxy';

export const dynamic = 'force-dynamic';

/**
 * POST /api/types/resolve — re-resolve the tenant's $ref edges and return the
 * dependency listing (resolver UI #3470, backed by REST #3459).
 *
 * Proxies to `POST /v1/types/{tenant_slug}/resolve`, which recomputes every edge's
 * resolved/unresolved status against the current registry, persists any change for the
 * tenant's own primitives, and returns the per-primitive dependency graph the resolver
 * view renders. No request body is required — caller scope comes from the JWT.
 */
export async function POST() {
  try {
    const ctx = await getAuthenticatedTenantContext();
    if (!ctx.ok) {
      return NextResponse.json({ success: false, error: ctx.error }, { status: ctx.status });
    }

    const { data, error, status } = await proxyRestPost(
      ctx.user,
      `/types/${encodeURIComponent(ctx.tenantSlug)}/resolve`
    );

    if (error) {
      return NextResponse.json({ success: false, error }, { status });
    }

    return NextResponse.json({ success: true, resolve: data });
  } catch (error) {
    console.error('Error resolving type references:', error);
    const message = error instanceof Error ? error.message : 'Internal server error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}
