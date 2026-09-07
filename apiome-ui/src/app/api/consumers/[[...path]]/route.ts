/**
 * API proxy for the consumer contract registry — CTG-4.1 (#4479)
 *
 * Forwards `/api/consumers/<projectRef>/...` to the REST service's tenant-scoped
 * `/v1/tenants/{tenantSlug}/projects/{projectRef}/...` endpoints, minting a short-lived JWT from
 * the authenticated session exactly like the other UI proxies. The tenant slug is resolved
 * server-side from the session, so the browser never needs it — and never gets to choose it.
 *
 * The browser talks to this route, not to REST: the RBAC decision
 * (`consumer_contracts:view|create|edit|delete`) belongs to the REST service holding the
 * session's identity, not to client code.
 *
 * ### Two sibling resources, one route, no reserved slugs
 *
 * REST keeps the picker's catalogue and the Pact import on sibling paths
 * (`consumer-surface`, `consumer-pact-imports`) so neither word is carved out of the consumer
 * slug space. This route preserves that: the two are addressed with a **colon-prefixed marker**
 * segment, and a colon is a character `consumer_slug_shape_check` forbids — so a consumer really
 * can be called `surface` and still be reachable.
 *
 * Examples:
 *   GET    /api/consumers/pets                        -> GET    …/projects/pets/consumers
 *   POST   /api/consumers/pets                        -> POST   …/projects/pets/consumers
 *   GET    /api/consumers/pets/:surface?version=1.0.0 -> GET    …/projects/pets/consumer-surface
 *   POST   /api/consumers/pets/:pact-imports          -> POST   …/projects/pets/consumer-pact-imports
 *   GET    /api/consumers/pets/billing                -> GET    …/projects/pets/consumers/billing
 *   PUT    /api/consumers/pets/billing/contract       -> PUT    …/consumers/billing/contract
 *   DELETE /api/consumers/pets/billing                -> DELETE …/projects/pets/consumers/billing
 */

import { NextRequest, NextResponse } from 'next/server';

import { getAuthenticatedTenantContext, type SessionUser } from '@lib/primitives-api-proxy';
import { restErrorMessage } from '@lib/rest-error-message';
import { createRestAuthHeaders, REST_API_BASE_URL } from '@lib/rest-auth';

/** The marker segment that addresses the picker's catalogue instead of a consumer. */
const SURFACE_MARKER = ':surface';

/** The marker segment that addresses the Pact import instead of a consumer. */
const PACT_IMPORT_MARKER = ':pact-imports';

/**
 * Build the upstream URL for a request.
 *
 * @param tenantSlug The session's tenant slug.
 * @param segments The path segments after `/api/consumers`, the first being the project ref.
 * @returns The absolute REST URL, or `null` when no project was named.
 */
function upstreamPath(tenantSlug: string, segments: string[]): string | null {
  const [projectRef, ...rest] = segments;
  if (!projectRef) return null;

  const base = `${REST_API_BASE_URL}/tenants/${encodeURIComponent(
    tenantSlug,
  )}/projects/${encodeURIComponent(projectRef)}`;

  if (rest[0] === SURFACE_MARKER) return `${base}/consumer-surface`;
  if (rest[0] === PACT_IMPORT_MARKER) return `${base}/consumer-pact-imports`;

  const subPath = rest.map(encodeURIComponent).join('/');
  return `${base}/consumers${subPath ? `/${subPath}` : ''}`;
}

/**
 * Forward the request to the REST API and translate the response back to the browser.
 *
 * @param request The incoming request.
 * @param segments The path segments after `/api/consumers`.
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
        { success: false, error: 'A project is required' },
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

    // 204 No Content (retiring a consumer) carries no body.
    if (response.status === 204) {
      return new NextResponse(null, { status: 204 });
    }

    const data = await response.json();
    if (!response.ok) {
      // Registry refusals arrive as `{detail: {code, message}}`, so the stable code survives to
      // the client rather than being flattened into prose.
      const detail = (data as { detail?: { code?: unknown } } | null)?.detail;
      const code =
        detail && typeof detail === 'object' && typeof detail.code === 'string'
          ? { code: detail.code }
          : {};
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

export async function POST(request: NextRequest, ctx: RouteCtx) {
  const { path } = await ctx.params;
  return forward(request, path ?? [], 'POST', true);
}

export async function PUT(request: NextRequest, ctx: RouteCtx) {
  const { path } = await ctx.params;
  return forward(request, path ?? [], 'PUT', true);
}

export async function PATCH(request: NextRequest, ctx: RouteCtx) {
  const { path } = await ctx.params;
  return forward(request, path ?? [], 'PATCH', true);
}

export async function DELETE(request: NextRequest, ctx: RouteCtx) {
  const { path } = await ctx.params;
  return forward(request, path ?? [], 'DELETE', false);
}
