/**
 * Shared plumbing for the project comment-thread BFF routes — COL-1.3 (#4515).
 *
 * Both routes (`route.ts`, the list; `summary/route.ts`, the counts) do the same three things
 * before anything of their own: decide the tenant from the session (never from the browser), sign
 * the caller's apiome-rest token, and read pages of `GET /v1/tenants/{tenant}/projects/{project}/
 * comment-threads`. apiome-rest enforces `projects:view` and resolves `mentions_me` from that
 * token, so these routes add no permission rules of their own.
 */

import { NextResponse } from 'next/server';
import { getAuthSession } from '@lib/auth/server-session';
import { getTenantById } from '@lib/db/helper';
import { createRestAuthHeaders, REST_API_BASE_URL, type SessionUserForRest } from '@lib/rest-auth';
import {
  REST_THREAD_PAGE_LIMIT,
  UNRESOLVED_COUNT_THREAD_CAP,
  type DiscussionThread,
  type DiscussionThreadPage,
} from '@lib/comment-discussion';

/** Who is asking, resolved from the session. */
export interface CommentThreadsAuth {
  /** The session user, as the REST token carries it. */
  user: SessionUserForRest;
  /** The caller's current tenant id. */
  tenantId: string;
  /** That tenant's slug, which apiome-rest's comment routes are addressed by. */
  tenantSlug: string;
}

/** A failed apiome-rest read, carrying the status to answer the browser with. */
export class RestCommentThreadsError extends Error {
  /** The HTTP status apiome-rest answered with (502 for an unreadable reply). */
  readonly status: number;

  /**
   * @param message - What went wrong, fit to show.
   * @param status - The HTTP status to pass on.
   */
  constructor(message: string, status: number) {
    super(message);
    this.name = 'RestCommentThreadsError';
    this.status = status;
  }
}

/**
 * Resolve the caller, or the error response that ends the request.
 *
 * @returns The caller's user and tenant, or a 401 (no session), 400 (no tenant selected) or 404
 *   (tenant not found) response.
 */
export async function resolveCommentThreadsAuth(): Promise<CommentThreadsAuth | NextResponse> {
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
 * The apiome-rest URL of a project's thread list.
 *
 * @param tenantSlug - The tenant slug.
 * @param projectRef - The project id or slug from the URL.
 * @param params - The (already sanitized) query.
 * @returns The absolute URL.
 */
export function restCommentThreadsUrl(
  tenantSlug: string,
  projectRef: string,
  params: URLSearchParams
): string {
  const query = params.toString();
  return (
    `${REST_API_BASE_URL}/tenants/${encodeURIComponent(tenantSlug)}` +
    `/projects/${encodeURIComponent(projectRef)}/comment-threads${query ? `?${query}` : ''}`
  );
}

/**
 * The message to show for a failed apiome-rest reply.
 *
 * apiome-rest's comment errors carry `detail: {code, message}`; FastAPI's validation errors carry
 * `detail: [...]`; everything else a string.
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

/**
 * Whether a parsed reply is a thread page.
 *
 * @param value - The parsed reply.
 * @returns True when it has a `threads` array and a numeric `total`.
 */
function isThreadPage(value: unknown): value is DiscussionThreadPage {
  const page = value as Partial<DiscussionThreadPage> | null;
  return Boolean(page) && Array.isArray(page?.threads) && typeof page?.total === 'number';
}

/**
 * Read one page of a project's threads from apiome-rest.
 *
 * @param auth - The caller.
 * @param projectRef - The project id or slug.
 * @param params - The sanitized query (`status`, `anchor_type`, `mentions_me`, `limit`, `offset`).
 * @returns The page.
 * @throws RestCommentThreadsError when apiome-rest refuses or answers with something unreadable.
 */
export async function fetchCommentThreadPage(
  auth: CommentThreadsAuth,
  projectRef: string,
  params: URLSearchParams
): Promise<DiscussionThreadPage> {
  const response = await fetch(restCommentThreadsUrl(auth.tenantSlug, projectRef, params), {
    method: 'GET',
    headers: createRestAuthHeaders(auth.user),
  });
  const raw = await response.text();
  let payload: unknown = null;
  try {
    payload = raw ? JSON.parse(raw) : null;
  } catch {
    payload = null;
  }
  if (!response.ok) {
    throw new RestCommentThreadsError(
      restErrorMessage(payload, raw || 'Failed to load comment threads'),
      response.status || 502
    );
  }
  if (!isThreadPage(payload)) {
    throw new RestCommentThreadsError('Unexpected reply from the comment API', 502);
  }
  return payload;
}

/**
 * Read a project's open threads, page by page, up to {@link UNRESOLVED_COUNT_THREAD_CAP}.
 *
 * @param auth - The caller.
 * @param projectRef - The project id or slug.
 * @param versionId - Only one version's threads, by (already sanitized) revision id (COL-2.2).
 * @returns The open threads read and apiome-rest's total of open threads (which can exceed the
 *   threads read when the cap is reached).
 * @throws RestCommentThreadsError when any page fails.
 */
export async function collectOpenCommentThreads(
  auth: CommentThreadsAuth,
  projectRef: string,
  versionId?: string | null
): Promise<{ threads: DiscussionThread[]; total: number }> {
  const threads: DiscussionThread[] = [];
  let total = 0;
  while (threads.length < UNRESOLVED_COUNT_THREAD_CAP) {
    const params = new URLSearchParams({
      status: 'open',
      limit: String(REST_THREAD_PAGE_LIMIT),
      offset: String(threads.length),
    });
    if (versionId) params.set('version', versionId);
    const page = await fetchCommentThreadPage(auth, projectRef, params);
    total = page.total;
    threads.push(...page.threads);
    if (page.threads.length === 0 || threads.length >= total) break;
  }
  return { threads: threads.slice(0, UNRESOLVED_COUNT_THREAD_CAP), total };
}

/**
 * The response for a failure while serving a comment-thread route.
 *
 * @param error - What was thrown.
 * @param label - Where it happened, for the server log.
 * @returns A `{success: false, error}` response with apiome-rest's status, or 500.
 */
export function commentThreadsErrorResponse(error: unknown, label: string): NextResponse {
  if (error instanceof RestCommentThreadsError) {
    return NextResponse.json({ success: false, error: error.message }, { status: error.status });
  }
  console.error(`${label}:`, error);
  const message = error instanceof Error ? error.message : 'Internal server error';
  return NextResponse.json({ success: false, error: message }, { status: 500 });
}
