/**
 * API proxy for Workspace → Single sign-on (EID-1.2, #5012).
 *
 *   GET|POST          /api/workspace-sso                               -> …/v1/tenants/{slug}/sso/providers
 *   GET|PATCH|DELETE  /api/workspace-sso/{id}                          -> …/sso/providers/{id}
 *   POST              /api/workspace-sso/{id}/domains                  -> …/sso/providers/{id}/domains
 *   DELETE            /api/workspace-sso/{id}/domains/{domain}         -> …/sso/providers/{id}/domains/{domain}
 *   POST              /api/workspace-sso/{id}/domains/{domain}/verify  -> …/sso/providers/{id}/domains/{domain}/verify
 *
 * The tenant slug comes from the session, so the browser never names a workspace — and never gets
 * to choose one. Who may call (owners and tenant admins, by session) is REST's decision; this
 * route adds no authority of its own. It forwards **only** the path shapes REST defines
 * (`workspaceSsoUpstreamPath`), so it cannot be steered at another tenant route.
 *
 * A refusal keeps REST's status and its stable `sso-*` code (`code`) beside the message, so the
 * page can tell "claimed by another workspace" from "checked too often". The request body may
 * carry a write-only secret: it is relayed verbatim and never logged.
 *
 * A successful write clears this process's routable-provider cache, so the next sign-in sees an
 * enabled provider, a disabled one or a newly verified domain at once.
 */

import { NextRequest, NextResponse } from 'next/server';

import { invalidateSsoProviderCache } from '@lib/auth/sso-provider-resolver';
import { getAuthenticatedTenantContext, type SessionUser } from '@lib/primitives-api-proxy';
import { restErrorMessage } from '@lib/rest-error-message';
import { createRestAuthHeaders, REST_API_BASE_URL } from '@lib/rest-auth';
import { workspaceSsoUpstreamPath } from '@lib/workspace-sso';

export const dynamic = 'force-dynamic';

/** What the browser is told when apiome-rest cannot be reached. */
const UNAVAILABLE = 'Single sign-on settings are unavailable (apiome-rest not reachable). Try again shortly.';

/**
 * The stable code of a REST refusal (`detail: {error, message}`), when it has one.
 *
 * @param data The parsed REST error body.
 * @returns e.g. `sso-domain-claimed`, or undefined.
 */
function refusalCode(data: unknown): string | undefined {
  const detail = (data as { detail?: unknown } | null)?.detail;
  const code = detail && typeof detail === 'object' ? (detail as { error?: unknown }).error : undefined;
  return typeof code === 'string' && code ? code : undefined;
}

/**
 * Forward one request to REST and translate the answer for the browser.
 *
 * @param request The incoming request.
 * @param segments The path segments after `/api/workspace-sso`.
 * @param method The HTTP method to forward.
 * @returns REST's body on success; `{ success: false, error, code? }` with REST's status otherwise.
 */
async function forward(request: NextRequest, segments: string[], method: string): Promise<NextResponse> {
  const context = await getAuthenticatedTenantContext();
  if (!context.ok) {
    return NextResponse.json({ success: false, error: context.error }, { status: context.status });
  }
  const path = workspaceSsoUpstreamPath(method, segments);
  if (!path) {
    return NextResponse.json({ success: false, error: 'No such single sign-on route.' }, { status: 404 });
  }

  const init: RequestInit = {
    method,
    headers: createRestAuthHeaders(context.user as SessionUser),
    cache: 'no-store',
  };
  if (method === 'POST' || method === 'PATCH') {
    const body = await request.text();
    if (body) {
      init.body = body;
      init.headers = { ...init.headers, 'Content-Type': 'application/json' };
    }
  }

  let response: Response;
  try {
    response = await fetch(
      `${REST_API_BASE_URL}/tenants/${encodeURIComponent(context.tenantSlug)}/${path}`,
      init,
    );
  } catch {
    return NextResponse.json({ success: false, error: UNAVAILABLE }, { status: 503 });
  }

  const data: unknown = await response.json().catch(() => ({}));
  if (!response.ok) {
    const code = refusalCode(data);
    return NextResponse.json(
      { success: false, error: restErrorMessage(data), ...(code ? { code } : {}) },
      { status: response.status >= 400 ? response.status : 502 },
    );
  }
  if (method !== 'GET') invalidateSsoProviderCache();
  return NextResponse.json(data, { status: response.status });
}

type RouteCtx = { params: Promise<{ path?: string[] }> };

export async function GET(request: NextRequest, ctx: RouteCtx) {
  return forward(request, (await ctx.params).path ?? [], 'GET');
}

export async function POST(request: NextRequest, ctx: RouteCtx) {
  return forward(request, (await ctx.params).path ?? [], 'POST');
}

export async function PATCH(request: NextRequest, ctx: RouteCtx) {
  return forward(request, (await ctx.params).path ?? [], 'PATCH');
}

export async function DELETE(request: NextRequest, ctx: RouteCtx) {
  return forward(request, (await ctx.params).path ?? [], 'DELETE');
}
