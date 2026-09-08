/**
 * API proxy for SDK generation settings — SDK-3.4 (#4494).
 *
 * Two scopes, one route, distinguished by whether a project is named:
 *
 *   GET|PUT|DELETE /api/sdk-settings         -> …/v1/tenants/{slug}/governance/sdk-generation-settings
 *   GET|PUT|DELETE /api/sdk-settings/<ref>   -> …/v1/projects/{slug}/<ref>/sdk-settings
 *
 * The tenant slug is resolved server-side from the session, exactly like the other UI proxies, so
 * the browser never needs it — and never gets to choose it. The RBAC decision
 * (`projects:view` / `projects:edit`) belongs to the REST service holding the session's identity,
 * not to client code.
 *
 * **The `errors` array survives.** An invalid settings body comes back as
 * `{detail: {code, errors: [...]}}` listing *every* problem, so a caller fixes them all in one
 * round trip. Flattening that into one prose line — which `restErrorMessage` alone would do —
 * would throw the rest away, so both the code and the list are lifted onto the envelope.
 */

import { NextRequest, NextResponse } from 'next/server';

import { getAuthenticatedTenantContext, type SessionUser } from '@lib/primitives-api-proxy';
import { restErrorMessage } from '@lib/rest-error-message';
import { createRestAuthHeaders, REST_API_BASE_URL } from '@lib/rest-auth';

/**
 * Build the upstream URL for a request.
 *
 * @param tenantSlug The session's tenant slug.
 * @param segments The path segments after `/api/sdk-settings` — none for the workspace scope, one
 *   project reference for a project's.
 * @returns The absolute REST URL, or `null` when more than one segment was supplied.
 */
function upstreamPath(tenantSlug: string, segments: string[]): string | null {
  const tenant = encodeURIComponent(tenantSlug);
  if (segments.length === 0) {
    return `${REST_API_BASE_URL}/tenants/${tenant}/governance/sdk-generation-settings`;
  }
  if (segments.length > 1) return null;
  return `${REST_API_BASE_URL}/projects/${tenant}/${encodeURIComponent(segments[0])}/sdk-settings`;
}

/**
 * Lift a REST refusal onto the envelope without losing its structure.
 *
 * @param data The parsed REST response body.
 * @returns The extra envelope fields — `code` and, for a validation refusal, `errors`.
 */
function refusalFields(data: unknown): { code?: string; errors?: string[] } {
  const detail = (data as { detail?: unknown } | null)?.detail;
  if (!detail || typeof detail !== 'object') return {};
  const shape = detail as { code?: unknown; errors?: unknown };
  return {
    ...(typeof shape.code === 'string' ? { code: shape.code } : {}),
    ...(Array.isArray(shape.errors) ? { errors: shape.errors.map(String) } : {}),
  };
}

/**
 * Forward the request to the REST API and translate the response back to the browser.
 *
 * @param request The incoming request.
 * @param segments The path segments after `/api/sdk-settings`.
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
      return NextResponse.json(
        { success: false, error: context.error },
        { status: context.status },
      );
    }

    const path = upstreamPath(context.tenantSlug, segments);
    if (!path) {
      return NextResponse.json(
        { success: false, error: 'Address either the workspace defaults or one project' },
        { status: 400 },
      );
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
    const data = await response.json();
    if (!response.ok) {
      return NextResponse.json(
        { success: false, error: restErrorMessage(data), ...refusalFields(data) },
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

export async function DELETE(request: NextRequest, ctx: RouteCtx) {
  const { path } = await ctx.params;
  return forward(request, path ?? [], 'DELETE', false);
}
