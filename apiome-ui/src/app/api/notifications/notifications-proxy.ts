/**
 * Shared plumbing for the notification BFF routes — COL-3.2 (#4522).
 *
 * The three routes beside this file (`route.ts`, `unread-count/route.ts`, `read/route.ts`)
 * all do the same two things before anything of their own: decide the tenant from the
 * session — never from the browser — and sign the caller's apiome-rest token.
 *
 * They add **no permission rules of their own**, and they must not: COL-3.1's routes need
 * only authentication because an inbox is the caller's own, which no `resource:action` can
 * express. The rows a token can reach are the rows belonging to the user that token
 * resolves to, decided upstream. This layer exists to keep the tenant slug and the signing
 * secret out of the browser, and to stop a hand-made request forwarding a parameter the UI
 * has never heard of.
 *
 * Modelled on `api/projects/[projectId]/comment-threads/comment-threads-proxy.ts`, which
 * makes the same three decisions for COL-1.3's thread reads.
 */

import { NextResponse } from 'next/server';

import { getAuthSession } from '@lib/auth/server-session';
import { getTenantById } from '@lib/db/helper';
import { createRestAuthHeaders, REST_API_BASE_URL, type SessionUserForRest } from '@lib/rest-auth';

/** Who is asking, resolved from the session. */
export interface NotificationsAuth {
  /** The session user, as the REST token carries it. */
  user: SessionUserForRest;
  /** The caller's current tenant id. */
  tenantId: string;
  /** That tenant's slug, which apiome-rest's notification routes are addressed by. */
  tenantSlug: string;
}

/**
 * Resolve the caller, or the response that ends the request.
 *
 * @returns The caller's user and tenant, or a 401 (no session), 400 (no tenant selected)
 *   or 404 (tenant not found) response.
 */
export async function resolveNotificationsAuth(): Promise<NotificationsAuth | NextResponse> {
  const session = await getAuthSession();
  if (!session?.user) {
    return NextResponse.json({ success: false, error: 'Unauthorized' }, { status: 401 });
  }
  const user = session.user as SessionUserForRest;
  const tenantId = user.current_tenant_id;
  if (!tenantId) {
    return NextResponse.json({ success: false, error: 'No tenant selected' }, { status: 400 });
  }
  const tenant = await getTenantById(tenantId);
  if (!tenant?.slug) {
    return NextResponse.json({ success: false, error: 'Tenant not found' }, { status: 404 });
  }
  return {
    user: {
      user_id: user.user_id,
      email: session.user.email,
      name: session.user.name,
      current_tenant_id: tenantId,
    },
    tenantId,
    tenantSlug: tenant.slug,
  };
}

/**
 * The apiome-rest URL of one of the inbox endpoints.
 *
 * @param tenantSlug - The tenant slug.
 * @param path - The sub-path under `/notifications`, e.g. `''`, `/unread-count`, `/read`.
 * @param params - The (already sanitized) query, if any.
 * @returns The absolute URL.
 */
export function restNotificationsUrl(
  tenantSlug: string,
  path: '' | '/unread-count' | '/read',
  params?: URLSearchParams
): string {
  const query = params?.toString() ?? '';
  return (
    `${REST_API_BASE_URL}/tenants/${encodeURIComponent(tenantSlug)}/notifications${path}` +
    (query ? `?${query}` : '')
  );
}

/**
 * The message to show for a failed apiome-rest reply.
 *
 * apiome-rest's notification errors carry `detail: {code, message}`; FastAPI's validation
 * errors carry `detail: [...]`; everything else a string.
 *
 * @param payload - The parsed reply, or null.
 * @param fallback - What to say when the reply says nothing usable.
 * @returns The message.
 */
export function restErrorMessage(payload: unknown, fallback: string): string {
  const detail = (payload as { detail?: unknown } | null)?.detail;
  if (typeof detail === 'string' && detail) return detail;
  if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
    const message = (detail as { message?: unknown }).message;
    if (typeof message === 'string' && message) return message;
  }
  if (Array.isArray(detail)) return 'The request was not valid';
  const error = (payload as { error?: unknown } | null)?.error;
  return typeof error === 'string' && error ? error : fallback;
}

/** A failed apiome-rest call, carrying the status to answer the browser with. */
export class RestNotificationsError extends Error {
  /** The HTTP status apiome-rest answered with (502 for an unreadable reply). */
  readonly status: number;

  /**
   * @param message - What went wrong, fit to show.
   * @param status - The HTTP status to pass on.
   */
  constructor(message: string, status: number) {
    super(message);
    this.name = 'RestNotificationsError';
    this.status = status;
  }
}

/**
 * Call one of the inbox endpoints and parse its reply.
 *
 * `cache: 'no-store'` on every call: an unread count is the one number on the screen that
 * must never be a cached answer the reader has already acted on.
 *
 * @param auth - The caller.
 * @param path - The sub-path under `/notifications`.
 * @param init - `method`, `body` and the sanitized `params`.
 * @returns The parsed reply.
 * @throws RestNotificationsError when apiome-rest refuses or answers with non-JSON.
 */
export async function callRestNotifications(
  auth: NotificationsAuth,
  path: '' | '/unread-count' | '/read',
  init: { method?: 'GET' | 'POST'; body?: unknown; params?: URLSearchParams } = {}
): Promise<unknown> {
  const method = init.method ?? 'GET';
  const response = await fetch(restNotificationsUrl(auth.tenantSlug, path, init.params), {
    method,
    headers: createRestAuthHeaders(auth.user),
    body: init.body === undefined ? undefined : JSON.stringify(init.body),
    cache: 'no-store',
  });

  const raw = await response.text();
  let payload: unknown = null;
  try {
    payload = raw ? JSON.parse(raw) : null;
  } catch {
    payload = null;
  }

  if (!response.ok) {
    throw new RestNotificationsError(
      restErrorMessage(payload, raw || 'Failed to read notifications'),
      response.status || 502
    );
  }
  if (!payload || typeof payload !== 'object') {
    throw new RestNotificationsError('Unexpected reply from the notification API', 502);
  }
  return payload;
}

/**
 * Turn a caught failure into the response to answer with.
 *
 * @param error - Whatever was caught.
 * @param fallback - What to say when the failure carried no message.
 * @returns A `{success: false, error}` response with the upstream status, or 500.
 */
export function notificationsErrorResponse(error: unknown, fallback: string): NextResponse {
  if (error instanceof RestNotificationsError) {
    return NextResponse.json({ success: false, error: error.message }, { status: error.status });
  }
  console.error(`${fallback}:`, error);
  const message = error instanceof Error && error.message ? error.message : fallback;
  return NextResponse.json({ success: false, error: message }, { status: 500 });
}
