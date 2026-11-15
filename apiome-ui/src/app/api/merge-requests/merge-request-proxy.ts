/**
 * Shared plumbing for the merge request BFF routes — COL-4.3 (#4527).
 *
 * Every route under `/api/merge-requests/[mergeRequestId]` first works out **who is asking** (the
 * session's user and tenant) and **which project** the merge request belongs to (one tenant-bound
 * query, `lib/db/merge-request-project.ts`), then reads or writes through apiome-rest, which
 * enforces `versions:view` / `versions:edit`. The project-scoped routes
 * (`/api/projects/[projectId]/draft-branches`, `…/merge-requests`) use {@link relayRest}.
 *
 * Failures are `{success: false, error, code?, detail?}` with apiome-rest's status: `code` is its
 * stable refusal code (`mr-*`, `review-*`, or the merge path's own), and `detail` carries the rest
 * of the refusal — `blockers` for `mr-not-ready`, `conflicts` for `mr-conflicts`.
 */

import { NextResponse } from 'next/server';
import { getAuthenticatedTenantContext, proxyRestGet, type SessionUser } from '@lib/primitives-api-proxy';
import { resolveMergeRequestProject, type MergeRequestProjectRow } from '@lib/db/merge-request-project';
import type { MergeRequestDetail } from '@lib/merge-requests';
import { restErrorCode, reviewFailure, reviewRouteError, upstreamStatus } from '../reviews/review-proxy';

/** Who is asking about which merge request. */
export interface MergeRequestContext {
  user: SessionUser;
  tenantId: string;
  tenantSlug: string;
  mergeRequestId: string;
  project: MergeRequestProjectRow;
}

/** An apiome-rest reply as the proxy helpers return it. */
interface RestReply {
  data: unknown;
  error: string | null;
  status: number;
  detail?: unknown;
}

/**
 * The failure response for a refused apiome-rest call, carrying its code and detail.
 *
 * @param reply - The proxy reply.
 * @returns `{success: false, error, code?, detail?}` with apiome-rest's status.
 */
export function restFailure(reply: RestReply): NextResponse {
  const code = restErrorCode(reply.detail);
  const detail = reply.detail && typeof reply.detail === 'object' && !Array.isArray(reply.detail) ? reply.detail : null;
  return NextResponse.json(
    {
      success: false,
      error: reply.error || 'Request failed',
      ...(code ? { code } : {}),
      ...(detail ? { detail } : {}),
    },
    { status: upstreamStatus(reply.status) }
  );
}

/**
 * Relay an apiome-rest reply: the body under `key` on success, {@link restFailure} otherwise.
 *
 * @param reply - The proxy reply.
 * @param key - Where the success body goes (`branch`, `mergeRequest` …); omit to spread it.
 * @param status - The success status.
 * @returns The response.
 */
export function relayRest(reply: RestReply, key?: string, status = 200): NextResponse {
  if (reply.error) return restFailure(reply);
  const body =
    key === undefined ? { success: true, ...(reply.data as Record<string, unknown>) } : { success: true, [key]: reply.data };
  return NextResponse.json(body, { status });
}

/**
 * apiome-rest's path of a project's sub-resource, relative to `REST_API_BASE_URL`.
 *
 * @param tenantSlug - The tenant.
 * @param projectId - The project.
 * @param suffix - E.g. `/draft-branches`.
 * @returns `/tenants/{slug}/projects/{project}{suffix}`.
 */
export function projectRestPath(tenantSlug: string, projectId: string, suffix: string): string {
  return `/tenants/${encodeURIComponent(tenantSlug)}/projects/${encodeURIComponent(projectId)}${suffix}`;
}

/**
 * Resolve the caller and the merge request's project, or the response that ends the request.
 *
 * @param mergeRequestId - The id from the URL.
 * @returns The context, or a 401 / 400 / 404 response.
 */
export async function resolveMergeRequestContext(mergeRequestId: string): Promise<MergeRequestContext | NextResponse> {
  const auth = await getAuthenticatedTenantContext();
  if (!auth.ok) return reviewFailure(auth.error, auth.status);
  const tenantId = auth.user.current_tenant_id as string;
  const project = await resolveMergeRequestProject(mergeRequestId, tenantId);
  if (!project) return reviewFailure('Merge request not found', 404, 'mr-not-found');
  return { user: auth.user, tenantId, tenantSlug: auth.tenantSlug, mergeRequestId, project };
}

/**
 * apiome-rest's path of the merge request.
 *
 * @param ctx - The context.
 * @param suffix - A sub-resource, e.g. `/merge`.
 * @returns `/tenants/{slug}/projects/{project}/merge-requests/{id}{suffix}`.
 */
export function mergeRequestRestPath(ctx: MergeRequestContext, suffix = ''): string {
  return projectRestPath(
    ctx.tenantSlug,
    ctx.project.id,
    `/merge-requests/${encodeURIComponent(ctx.mergeRequestId)}${suffix}`
  );
}

/**
 * Whether a parsed reply is a merge request detail.
 *
 * @param value - The reply.
 * @returns True when it has a merge request with an id and a readiness block.
 */
export function isMergeRequestDetail(value: unknown): value is MergeRequestDetail {
  const detail = value as Partial<MergeRequestDetail> | null;
  return typeof detail?.merge_request?.id === 'string' && Array.isArray(detail?.readiness?.blockers);
}

/**
 * Read the merge request from apiome-rest — which is also the `versions:view` check.
 *
 * @param ctx - The context.
 * @returns The detail, or the failure response.
 */
export async function fetchMergeRequestDetail(ctx: MergeRequestContext): Promise<MergeRequestDetail | NextResponse> {
  const reply = await proxyRestGet(ctx.user, mergeRequestRestPath(ctx));
  if (reply.error) return restFailure(reply);
  if (!isMergeRequestDetail(reply.data)) return reviewFailure('Unexpected reply from the merge request API', 502);
  return reply.data;
}

/**
 * The response for an unexpected failure while serving a merge request route.
 *
 * @param error - What was thrown.
 * @param label - Where it happened, for the server log.
 * @returns A 500 `{success: false, error}`.
 */
export function mergeRequestRouteError(error: unknown, label: string): NextResponse {
  return reviewRouteError(error, label);
}
