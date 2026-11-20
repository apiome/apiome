/**
 * Shared plumbing for the stored overlay chain proxy routes — GVM-4.3 (#5878).
 *
 * ```
 * /api/versions/{v}/overlays?projectId=…             → /v1/versions/{t}/{p}/{v}/overlays
 * /api/versions/{v}/overlays/preview?projectId=…     → …/overlays/preview   (GET, POST with a draft)
 * /api/versions/{v}/overlays/apply?projectId=…       → …/overlays/apply     (COA-2.7)
 * /api/versions/{v}/overlays/{overlayId}?projectId=… → …/overlays/{overlayId}
 * ```
 *
 * The tenant comes from the session, never from the browser. apiome-rest enforces
 * `versions:view` / `versions:edit` and the published-revision guard; this layer passes its refusal
 * `code` (for example `overlay-version-published`) through so the panel can say why.
 */

import { NextRequest, NextResponse } from 'next/server';

import {
  getAuthenticatedTenantContext,
  proxyRestDelete,
  proxyRestGet,
  proxyRestPost,
  proxyRestPut,
} from '@lib/primitives-api-proxy';

/** The verbs the overlay routes forward. */
export type VersionOverlaysMethod = 'GET' | 'POST' | 'PUT' | 'DELETE';

/**
 * The stable refusal code inside a REST `detail`, when it carries one.
 *
 * @param detail The `detail` of a failed REST reply.
 * @returns The code, or null.
 */
function refusalCode(detail: unknown): string | null {
  if (detail && typeof detail === 'object' && 'code' in detail) {
    const code = (detail as { code?: unknown }).code;
    return typeof code === 'string' && code ? code : null;
  }
  return null;
}

/**
 * Forward one overlay-chain request for the session's tenant.
 *
 * @param request The incoming request; its `projectId` query parameter is required.
 * @param versionId The revision id from the route.
 * @param method The HTTP verb.
 * @param suffix The path after `/overlays` (`''`, `'/preview'`, `'/apply'` or `'/<encoded id>'`).
 * @param body The JSON body for POST / PUT.
 * @returns `{success: true, data}` with REST's status, or `{success: false, error, code}`.
 */
export async function forwardVersionOverlays(
  request: NextRequest,
  versionId: string,
  method: VersionOverlaysMethod,
  suffix = '',
  body?: unknown
): Promise<NextResponse> {
  try {
    const ctx = await getAuthenticatedTenantContext();
    if (!ctx.ok) {
      return NextResponse.json({ success: false, error: ctx.error }, { status: ctx.status });
    }
    const projectId = new URL(request.url).searchParams.get('projectId');
    if (!projectId) {
      return NextResponse.json({ success: false, error: 'projectId is required' }, { status: 400 });
    }
    const path = `/versions/${encodeURIComponent(ctx.tenantSlug)}/${encodeURIComponent(
      projectId
    )}/${encodeURIComponent(versionId)}/overlays${suffix}`;

    const result =
      method === 'GET'
        ? await proxyRestGet(ctx.user, path)
        : method === 'POST'
          ? await proxyRestPost(ctx.user, path, body)
          : method === 'PUT'
            ? await proxyRestPut(ctx.user, path, body)
            : await proxyRestDelete(ctx.user, path);

    if (result.error) {
      const detail = 'detail' in result ? result.detail : undefined;
      return NextResponse.json(
        { success: false, error: result.error, code: refusalCode(detail) },
        { status: result.status || 500 }
      );
    }
    return NextResponse.json({ success: true, data: result.data }, { status: result.status === 204 ? 200 : result.status });
  } catch (error) {
    console.error('[version-overlays] proxy failed', error);
    return NextResponse.json({ success: false, error: 'Overlay request failed' }, { status: 502 });
  }
}

/**
 * Read a JSON request body, or answer 400.
 *
 * @param request The incoming POST / PUT.
 * @returns The parsed body, or the 400 response to return as is.
 */
export async function readOverlayBody(request: NextRequest): Promise<unknown | NextResponse> {
  try {
    return await request.json();
  } catch {
    return NextResponse.json({ success: false, error: 'A JSON body is required' }, { status: 400 });
  }
}
