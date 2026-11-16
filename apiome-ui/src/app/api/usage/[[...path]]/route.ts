/**
 * API proxy for the usage data controls — RDG-5.4 (#5789)
 *
 * Forwards the browser's `/api/usage/...` calls to the REST service's tenant-scoped usage
 * endpoints. It mints the REST credentials from the session, like every other UI proxy. The tenant slug is resolved
 * server-side from the session, so the browser never chooses it. REST makes every permission
 * decision.
 *
 * The path mapping lives in `lib/usage-proxy-path.ts` (pure, tested on its own).
 *
 * Examples:
 *   GET   /api/usage/:retention                      -> GET   …/usage/retention
 *   PUT   /api/usage/:retention                      -> PUT   …/usage/retention
 *   PATCH /api/usage/:toolsets/<id>/body-samples     -> PATCH …/agent-toolsets/<id>/body-samples
 *   GET   /api/usage/pets/sources                    -> GET   …/projects/pets/usage/sources
 *   PATCH /api/usage/pets/sources/<id>               -> PATCH …/projects/pets/usage/sources/<id>
 *   GET   /api/usage/pets/export?format=csv&days=30  -> GET   …/projects/pets/usage/export (streamed file)
 *
 * JSON answers are wrapped as `{success, data}` or `{success: false, error, code?}`. The export is
 * passed through as the file REST streams, with its `Content-Disposition`, so the browser downloads it.
 */

import { NextRequest, NextResponse } from 'next/server';

import { getAuthenticatedTenantContext, type SessionUser } from '@lib/primitives-api-proxy';
import { restErrorMessage } from '@lib/rest-error-message';
import { createRestAuthHeaders, REST_API_BASE_URL } from '@lib/rest-auth';
import { isUsageExport, usageUpstreamPath } from '@lib/usage-proxy-path';

/**
 * Forward the request to the REST API and translate the response back to the browser.
 *
 * @param request The incoming request.
 * @param segments The path segments after `/api/usage`.
 * @param method The HTTP method to forward.
 * @param withBody Whether to forward the request body.
 * @returns The response to send to the browser.
 */
async function forward(
  request: NextRequest,
  segments: string[],
  method: string,
  withBody: boolean,
): Promise<NextResponse> {
  try {
    const context = await getAuthenticatedTenantContext();
    if (!context.ok) {
      return NextResponse.json({ success: false, error: context.error }, { status: context.status });
    }
    const path = usageUpstreamPath(REST_API_BASE_URL, context.tenantSlug, segments);
    if (!path) {
      return NextResponse.json({ success: false, error: 'Unknown usage resource' }, { status: 404 });
    }
    const init: RequestInit = {
      method,
      headers: createRestAuthHeaders(context.user as SessionUser),
      cache: 'no-store',
    };
    if (withBody) {
      const body = await request.text();
      if (body) init.body = body;
    }
    const response = await fetch(`${path}${request.nextUrl.search || ''}`, init);

    if (isUsageExport(segments) && response.ok && response.body) {
      const headers = new Headers({ 'Cache-Control': 'no-store' });
      for (const name of ['content-type', 'content-disposition']) {
        const value = response.headers.get(name);
        if (value) headers.set(name, value);
      }
      return new NextResponse(response.body, { status: 200, headers });
    }

    const data = await response.json().catch(() => null);
    if (!response.ok) {
      const detail = (data as { detail?: { code?: unknown } } | null)?.detail;
      const code =
        detail && typeof detail === 'object' && typeof detail.code === 'string' ? { code: detail.code } : {};
      return NextResponse.json(
        { success: false, error: restErrorMessage(data), ...code },
        { status: response.status },
      );
    }
    return NextResponse.json({ success: true, data });
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Internal server error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}

type RouteCtx = { params: Promise<{ path?: string[] }> };

export async function GET(request: NextRequest, ctx: RouteCtx) {
  const { path } = await ctx.params;
  return forward(request, path ?? [], 'GET', false);
}

export async function PUT(request: NextRequest, ctx: RouteCtx) {
  const { path } = await ctx.params;
  return forward(request, path ?? [], 'PUT', true);
}

export async function PATCH(request: NextRequest, ctx: RouteCtx) {
  const { path } = await ctx.params;
  return forward(request, path ?? [], 'PATCH', true);
}
