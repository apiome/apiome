/**
 * Shared plumbing for the `$ref` hygiene proxy routes — COA-2.8 (#7051).
 *
 * ```
 * GET    /api/projects/{p}/references?version=…   → /v1/projects/{t}/{p}/references
 * POST   /api/projects/{p}/references/refresh     → …/references/refresh
 * PUT    /api/projects/{p}/references/pin         → …/references/pin
 * DELETE /api/projects/{p}/references/pin?url=…   → …/references/pin?url=…
 * GET    /api/external-ref-policy                 → /v1/tenants/{t}/governance/external-ref-policy
 * PUT    /api/external-ref-policy                 → (administrators only; REST enforces it)
 * ```
 *
 * The tenant comes from the session, never from the browser. apiome-rest enforces the
 * permissions; this layer passes a refusal's `code` (for example `ref-not-fetched`) through.
 */

import { NextRequest, NextResponse } from 'next/server';

import {
  getAuthenticatedTenantContext,
  proxyRestDelete,
  proxyRestGet,
  proxyRestPost,
  proxyRestPut,
} from '@lib/primitives-api-proxy';

/** The verbs the routes forward. */
export type ReferencesMethod = 'GET' | 'POST' | 'PUT' | 'DELETE';

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
 * Forward one request for the session's tenant.
 *
 * @param method The HTTP verb.
 * @param path A function of the tenant slug giving the REST path (after `/v1`), query included.
 * @param body The JSON body for POST / PUT.
 * @returns `{success: true, data}` with REST's status, or `{success: false, error, code}`.
 */
export async function forwardReferences(
  method: ReferencesMethod,
  path: (tenantSlug: string) => string,
  body?: unknown
): Promise<NextResponse> {
  try {
    const ctx = await getAuthenticatedTenantContext();
    if (!ctx.ok) {
      return NextResponse.json({ success: false, error: ctx.error }, { status: ctx.status });
    }
    const restPath = path(ctx.tenantSlug);
    const result =
      method === 'GET'
        ? await proxyRestGet(ctx.user, restPath)
        : method === 'POST'
          ? await proxyRestPost(ctx.user, restPath, body)
          : method === 'PUT'
            ? await proxyRestPut(ctx.user, restPath, body)
            : await proxyRestDelete(ctx.user, restPath);
    if (result.error) {
      const detail = 'detail' in result ? result.detail : undefined;
      return NextResponse.json(
        { success: false, error: result.error, code: refusalCode(detail) },
        { status: result.status || 500 }
      );
    }
    return NextResponse.json({ success: true, data: result.data }, { status: result.status || 200 });
  } catch (error) {
    console.error('[project-references] proxy failed', error);
    return NextResponse.json({ success: false, error: 'References request failed' }, { status: 502 });
  }
}

/**
 * The REST path of a project's references (or a path under it).
 *
 * @param tenantSlug The session's tenant.
 * @param projectId The project.
 * @param suffix `''`, `'/refresh'` or `'/pin'`.
 */
export function referencesPath(tenantSlug: string, projectId: string, suffix = ''): string {
  return `/projects/${encodeURIComponent(tenantSlug)}/${encodeURIComponent(projectId)}/references${suffix}`;
}

/**
 * Read a JSON request body, or answer 400.
 *
 * @param request The incoming POST / PUT.
 * @returns The parsed body, or the 400 response to return as is.
 */
export async function readReferencesBody(request: NextRequest): Promise<unknown | NextResponse> {
  try {
    return await request.json();
  } catch {
    return NextResponse.json({ success: false, error: 'A JSON body is required' }, { status: 400 });
  }
}
