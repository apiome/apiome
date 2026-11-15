/**
 * Proxy GET for a project's generator compatibility manifest — SGD-2.1 (#4735).
 *
 * `GET /api/projects/{projectId}/sdk-compatibility?version=<label|revision id>` forwards to apiome-rest's
 * `GET /v1/tenants/{tenant}/projects/{projectId}/sdk-compatibility`, the route `apiome sdk compatibility`
 * reads too. The tenant comes from the session, never the browser; `projects:view` is decided by the
 * REST service. Only `version` is forwarded.
 */

import { NextRequest, NextResponse } from 'next/server';

import { getAuthenticatedTenantContext, type SessionUser } from '@lib/primitives-api-proxy';
import { restErrorMessage } from '@lib/rest-error-message';
import { createRestAuthHeaders, REST_API_BASE_URL } from '@lib/rest-auth';

type RouteCtx = { params: Promise<{ projectId: string }> };

export async function GET(request: NextRequest, ctx: RouteCtx): Promise<NextResponse> {
  try {
    const context = await getAuthenticatedTenantContext();
    if (!context.ok) {
      return NextResponse.json({ success: false, error: context.error }, { status: context.status });
    }
    const { projectId } = await ctx.params;
    const version = request.nextUrl.searchParams.get('version');
    const query = version ? `?${new URLSearchParams({ version }).toString()}` : '';
    const url = `${REST_API_BASE_URL}/tenants/${encodeURIComponent(context.tenantSlug)}/projects/${encodeURIComponent(
      projectId,
    )}/sdk-compatibility${query}`;
    const response = await fetch(url, {
      headers: createRestAuthHeaders(context.user as SessionUser),
      cache: 'no-store',
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const code = (data as { detail?: { code?: unknown } })?.detail?.code;
      return NextResponse.json(
        { success: false, error: restErrorMessage(data), ...(typeof code === 'string' ? { code } : {}) },
        { status: response.status },
      );
    }
    return NextResponse.json({ success: true, data });
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Internal server error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}
