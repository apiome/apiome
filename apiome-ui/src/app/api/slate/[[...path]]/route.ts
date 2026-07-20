/**
 * API proxy for managed Slate hosting — APX-3.1 (private-suite#2456)
 *
 * Optional catch-all proxy forwarding `/api/slate/<...>` to the REST service's
 * `/v1/slate/<...>` deployment control plane, minting a short-lived JWT from the NextAuth
 * session exactly like the other UI proxies.
 *
 * Unlike `/api/style-guides`, the Slate endpoints are **not** tenant-slug-scoped in their
 * path: the REST layer reads the tenant from the JWT and answers 404 (not 403) on a scope
 * miss, so a cross-tenant probe cannot confirm a site or environment exists. Putting the
 * slug in the URL here would hand the browser a value it has no reason to know, and would
 * make the proxy — rather than the token — the thing that decides tenancy.
 *
 * Examples:
 *   GET  /api/slate/sites/{id}/releases            -> GET  /v1/slate/sites/{id}/releases
 *   GET  /api/slate/releases/{id}                  -> GET  /v1/slate/releases/{id}
 *   GET  /api/slate/environments/{id}              -> GET  /v1/slate/environments/{id}
 *   POST /api/slate/environments/{id}/promote      -> POST /v1/slate/environments/{id}/promote
 *   POST /api/slate/environments/{id}/rollback     -> POST /v1/slate/environments/{id}/rollback
 *   POST /api/slate/sites/{id}/retention           -> POST /v1/slate/sites/{id}/retention
 *
 * Refusals matter here. The control plane answers 409 with a named `reason` and an
 * operator-facing `message`; this proxy forwards the REST status and body through unchanged
 * rather than collapsing them to a generic failure, because the Release Center renders that
 * sentence as the reason a control is disabled.
 */

import { NextRequest, NextResponse } from 'next/server';

import {
  getAuthenticatedTenantContext,
  proxyRestGet,
  proxyRestPost,
} from '@lib/primitives-api-proxy';

/** Route segment params; Next 15+ delivers these as a promise. */
type RouteContext = { params: Promise<{ path?: string[] }> };

/**
 * Build the `/slate/...` REST path (including query string) for an incoming request.
 *
 * @param request - The incoming proxy request, whose search params are preserved so
 *                  `environmentId` filters reach the control plane.
 * @param segments - Path segments after `/api/slate`.
 * @returns The REST path to forward to, relative to the `/v1` base.
 */
function restPath(request: NextRequest, segments: string[] | undefined): string {
  const suffix = (segments ?? []).map(encodeURIComponent).join('/');
  const query = request.nextUrl.search;
  return `/slate${suffix ? `/${suffix}` : ''}${query}`;
}

/**
 * Forward a proxied result, preserving the control plane's status and body.
 *
 * A 409 refusal carries the reason the Release Center shows the operator, so it must not be
 * flattened into a generic error.
 *
 * @param result - The normalized proxy result.
 * @returns The Next response to return to the browser.
 */
function forward(result: { data: unknown; error: string | null; status: number }): NextResponse {
  if (result.error !== null) {
    return NextResponse.json(
      { error: result.error, detail: result.data ?? undefined },
      { status: result.status }
    );
  }
  return NextResponse.json(result.data, { status: result.status });
}

/**
 * Read from the deployment control plane.
 *
 * @param request - The incoming request.
 * @param context - Route params carrying the path segments.
 * @returns The proxied REST response.
 */
export async function GET(request: NextRequest, context: RouteContext): Promise<NextResponse> {
  const auth = await getAuthenticatedTenantContext();
  if (!auth.ok) {
    return NextResponse.json({ error: auth.error }, { status: auth.status });
  }

  const { path } = await context.params;
  return forward(await proxyRestGet(auth.user, restPath(request, path)));
}

/**
 * Record a release, promote, roll back, or run retention.
 *
 * A request body is optional: rollback and retention take none.
 *
 * @param request - The incoming request.
 * @param context - Route params carrying the path segments.
 * @returns The proxied REST response.
 */
export async function POST(request: NextRequest, context: RouteContext): Promise<NextResponse> {
  const auth = await getAuthenticatedTenantContext();
  if (!auth.ok) {
    return NextResponse.json({ error: auth.error }, { status: auth.status });
  }

  // An empty body is legitimate; treat unparseable JSON as "no body" rather than a 400, so a
  // bodyless rollback does not fail before it reaches the gate that would explain itself.
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    body = undefined;
  }

  const { path } = await context.params;
  return forward(await proxyRestPost(auth.user, restPath(request, path), body));
}
