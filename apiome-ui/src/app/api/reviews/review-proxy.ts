/**
 * Shared plumbing for the review page's BFF routes — COL-2.2 (#4518).
 *
 * Every route under `/api/reviews/[reviewId]` does the same things before its own work:
 *
 * 1. **Who is asking** — the session's user and tenant (never the browser's say-so), via
 *    `getAuthenticatedTenantContext`.
 * 2. **Which project** — the page's URL carries only the review id, but apiome-rest addresses reviews
 *    by project, so the review's project is read with one tenant-bound query
 *    (`lib/db/review-project.ts`). A review of another tenant is a 404 here.
 * 3. **May they see it** — the routes then read the review from apiome-rest, which enforces
 *    `projects:view`; the Changes and Spec routes also read the project's versions, which enforces
 *    `versions:view`. No route builds or returns anything before those reads succeed.
 *
 * Failures are `{success: false, error, code?}` with apiome-rest's status, `code` being its stable
 * `review-*` refusal code when it sent one.
 */

import { NextResponse } from 'next/server';
import { getAuthenticatedTenantContext, proxyRestGet, type SessionUser } from '@lib/primitives-api-proxy';
import { resolveReviewProject, type ReviewProjectRow } from '@lib/db/review-project';
import type { RevisionRow, ReviewDetail } from '@lib/review-page';

/** Who is asking about which review. */
export interface ReviewContext {
  /** The session user, as the REST token carries it. */
  user: SessionUser;
  /** The caller's current tenant id. */
  tenantId: string;
  /** That tenant's slug, which apiome-rest's routes are addressed by. */
  tenantSlug: string;
  /** The review id from the URL. */
  reviewId: string;
  /** The review's project. */
  project: ReviewProjectRow;
}

/** A project revision as apiome-rest's version list returns it. */
export interface ProjectRevisionRow extends RevisionRow {
  project_id?: string;
  /** The revision note (`versions.description`), which the document uses as its description. */
  shortMessage?: string | null;
}

/**
 * A failure response.
 *
 * @param error - What went wrong, fit to show.
 * @param status - The HTTP status.
 * @param code - apiome-rest's refusal code, when there is one.
 * @returns `{success: false, error, code?}`.
 */
export function reviewFailure(error: string, status: number, code?: string | null): NextResponse {
  return NextResponse.json({ success: false, error, ...(code ? { code } : {}) }, { status });
}

/**
 * The stable code inside an apiome-rest `detail`.
 *
 * @param detail - The reply's `detail` (a string, an object with `code`, or a validation array).
 * @returns The code, or null.
 */
export function restErrorCode(detail: unknown): string | null {
  if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
    const code = (detail as { code?: unknown }).code;
    return typeof code === 'string' && code ? code : null;
  }
  return null;
}

/**
 * The status to answer a failed upstream call with.
 *
 * @param status - apiome-rest's status.
 * @returns It when it is an error status, 502 otherwise.
 */
export function upstreamStatus(status: number): number {
  return status >= 400 ? status : 502;
}

/**
 * Resolve the caller and the review's project, or the response that ends the request.
 *
 * @param reviewId - The review id from the URL.
 * @returns The context, or a 401 / 400 / 404 response.
 */
export async function resolveReviewContext(reviewId: string): Promise<ReviewContext | NextResponse> {
  const auth = await getAuthenticatedTenantContext();
  if (!auth.ok) return reviewFailure(auth.error, auth.status);
  const tenantId = auth.user.current_tenant_id as string;
  const project = await resolveReviewProject(reviewId, tenantId);
  if (!project) return reviewFailure('Review not found', 404, 'review-not-found');
  return { user: auth.user, tenantId, tenantSlug: auth.tenantSlug, reviewId, project };
}

/**
 * The apiome-rest path of the review, relative to `REST_API_BASE_URL`.
 *
 * @param ctx - The context.
 * @param suffix - A sub-resource, e.g. `/decision`.
 * @returns `/tenants/{slug}/projects/{project}/reviews/{id}{suffix}`.
 */
export function reviewRestPath(ctx: ReviewContext, suffix = ''): string {
  return (
    `/tenants/${encodeURIComponent(ctx.tenantSlug)}/projects/${encodeURIComponent(ctx.project.id)}` +
    `/reviews/${encodeURIComponent(ctx.reviewId)}${suffix}`
  );
}

/**
 * Whether a parsed reply is a review detail.
 *
 * @param value - The reply.
 * @returns True when it has a review with an id and version, and a reviewers array.
 */
export function isReviewDetail(value: unknown): value is ReviewDetail {
  const detail = value as Partial<ReviewDetail> | null;
  return (
    Boolean(detail?.review) &&
    typeof detail?.review?.id === 'string' &&
    typeof detail?.review?.version_id === 'string' &&
    Array.isArray(detail?.reviewers)
  );
}

/**
 * Read the review from apiome-rest — which is also the `projects:view` check.
 *
 * @param ctx - The context.
 * @returns The review, or the failure response.
 */
export async function fetchReviewDetail(ctx: ReviewContext): Promise<ReviewDetail | NextResponse> {
  const { data, error, status } = await proxyRestGet(ctx.user, reviewRestPath(ctx));
  if (error) return reviewFailure(error, upstreamStatus(status));
  if (!isReviewDetail(data)) return reviewFailure('Unexpected reply from the review API', 502);
  return data;
}

/**
 * Read the project's revisions from apiome-rest — which is also the `versions:view` check.
 *
 * @param ctx - The context.
 * @returns The revisions, or the failure response.
 */
export async function fetchProjectRevisions(ctx: ReviewContext): Promise<ProjectRevisionRow[] | NextResponse> {
  const path = `/versions/${encodeURIComponent(ctx.tenantSlug)}/${encodeURIComponent(ctx.project.id)}`;
  const { data, error, status } = await proxyRestGet(ctx.user, path);
  if (error) return reviewFailure(error, upstreamStatus(status));
  const rows = Array.isArray(data) ? data : (data as { versions?: unknown } | null)?.versions;
  if (!Array.isArray(rows)) return reviewFailure('Unexpected reply from the versions API', 502);
  return rows as ProjectRevisionRow[];
}

/**
 * The response for an unexpected failure while serving a review route.
 *
 * @param error - What was thrown.
 * @param label - Where it happened, for the server log.
 * @returns A 500 `{success: false, error}`.
 */
export function reviewRouteError(error: unknown, label: string): NextResponse {
  console.error(`${label}:`, error);
  return reviewFailure(error instanceof Error ? error.message : 'Internal server error', 500);
}
