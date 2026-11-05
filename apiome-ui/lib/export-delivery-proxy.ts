/**
 * Shared plumbing for the export delivery proxy routes (MFX-38.4, #4331).
 *
 * `/api/export/delivery-profiles/**`, `/api/export/jobs/{jobId}/deliveries` and
 * `/api/export/storage-credentials` forward to the REST layer's `/v1/export/{tenant}/…` routes with
 * the session's tenant. Every one answers the same envelope: `{ success: true, data }`, or
 * `{ success: false, error, code?, errors? }` — a REST refusal's `code` and its per-field `errors`
 * ride along, so a form can mark every bad field at once.
 */

import { NextResponse } from 'next/server';
import {
  getAuthenticatedTenantContext,
  proxyRestDelete,
  proxyRestGet,
  proxyRestPatch,
  proxyRestPost,
} from '@lib/primitives-api-proxy';

/** The HTTP verbs the delivery routes forward. */
export type DeliveryProxyMethod = 'GET' | 'POST' | 'PATCH' | 'DELETE';

/** The fields of a REST refusal's `detail` the envelope carries on. */
function refusalFields(detail: unknown): { code?: string; errors?: string[] } {
  if (!detail || typeof detail !== 'object') return {};
  const { code, errors } = detail as { code?: unknown; errors?: unknown };
  return {
    ...(typeof code === 'string' ? { code } : {}),
    ...(Array.isArray(errors) ? { errors: errors.map(String) } : {}),
  };
}

/**
 * Forward one request to `/v1/export/{tenant}{subPath}` and answer the envelope.
 *
 * @param method The verb.
 * @param subPath The path below `/export/{tenant}` — already URL-encoded, with its query string.
 * @param body The JSON body for `POST` / `PATCH`.
 * @returns The `NextResponse`, with the REST status.
 */
export async function forwardExportDelivery(
  method: DeliveryProxyMethod,
  subPath: string,
  body?: unknown,
): Promise<NextResponse> {
  try {
    const ctx = await getAuthenticatedTenantContext();
    if (!ctx.ok) {
      return NextResponse.json({ success: false, error: ctx.error }, { status: ctx.status });
    }
    const path = `/export/${encodeURIComponent(ctx.tenantSlug)}${subPath}`;
    const result =
      method === 'GET'
        ? await proxyRestGet(ctx.user, path)
        : method === 'POST'
          ? await proxyRestPost(ctx.user, path, body)
          : method === 'PATCH'
            ? await proxyRestPatch(ctx.user, path, body)
            : await proxyRestDelete(ctx.user, path);
    if (result.error) {
      const detail = 'detail' in result ? result.detail : undefined;
      return NextResponse.json(
        { success: false, error: result.error, ...refusalFields(detail) },
        { status: result.status },
      );
    }
    // A 204 has no body; the envelope still answers 200 so the client can parse it.
    return NextResponse.json(
      { success: true, data: result.data ?? null },
      { status: result.status === 204 ? 200 : result.status },
    );
  } catch (error) {
    console.error(`Error forwarding export delivery ${method} ${subPath}:`, error);
    const message = error instanceof Error ? error.message : 'Internal server error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}

/**
 * Read a request's JSON object body, or answer `400`.
 *
 * @param request The incoming request.
 * @returns The body, or a `NextResponse` refusal.
 */
export async function jsonBodyOr400(request: Request): Promise<Record<string, unknown> | NextResponse> {
  const body = await request.json().catch(() => null);
  if (!body || typeof body !== 'object' || Array.isArray(body)) {
    return NextResponse.json({ success: false, error: 'Missing request body' }, { status: 400 });
  }
  return body as Record<string, unknown>;
}
