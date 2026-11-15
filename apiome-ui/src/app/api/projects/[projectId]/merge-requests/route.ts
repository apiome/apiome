/**
 * Merge requests of a project — COL-4.3 (#4527).
 *
 * GET  /api/projects/[projectId]/merge-requests?state=open|merged|closed →
 *   `{success, merge_requests, count, total, limit, offset}`
 * POST /api/projects/[projectId]/merge-requests — body
 *   `{source_branch, target_branch, title, description?, reviewers}` → `{success, mergeRequest}` (201)
 *
 * Proxies `…/v1/tenants/{tenant}/projects/{project}/merge-requests`, which enforces `versions:view` /
 * `versions:edit` and requests the review of the branch tip from the named reviewers.
 */

import { NextRequest } from 'next/server';
import { getAuthenticatedTenantContext, proxyRestGet, proxyRestPost } from '@lib/primitives-api-proxy';
import { MERGE_REQUEST_FILTERS, type MergeRequestState } from '@lib/merge-requests';
import { reviewFailure } from '../../../reviews/review-proxy';
import { mergeRequestRouteError, projectRestPath, relayRest } from '../../../merge-requests/merge-request-proxy';

type Params = { params: Promise<{ projectId: string }> };

/**
 * List the project's merge requests, optionally in one state.
 *
 * @param request - The browser's request (`?state=`).
 * @param context - The route parameters.
 * @returns The page, or a failure envelope.
 */
export async function GET(request: NextRequest, { params }: Params) {
  try {
    const auth = await getAuthenticatedTenantContext();
    if (!auth.ok) return reviewFailure(auth.error, auth.status);
    const { projectId } = await params;
    const state = request.nextUrl.searchParams.get('state');
    const query = state && MERGE_REQUEST_FILTERS.includes(state as MergeRequestState) ? `?state=${state}` : '';
    return relayRest(
      await proxyRestGet(auth.user, projectRestPath(auth.tenantSlug, projectId, `/merge-requests${query}`))
    );
  } catch (error) {
    return mergeRequestRouteError(error, 'merge requests GET');
  }
}

/**
 * Open a merge request.
 *
 * @param request - The browser's request, carrying the form.
 * @param context - The route parameters.
 * @returns `{success: true, mergeRequest}` (201) or a failure envelope.
 */
export async function POST(request: NextRequest, { params }: Params) {
  try {
    const auth = await getAuthenticatedTenantContext();
    if (!auth.ok) return reviewFailure(auth.error, auth.status);
    const { projectId } = await params;
    const body = (await request.json().catch(() => null)) as Record<string, unknown> | null;
    if (!body || typeof body.source_branch !== 'string') return reviewFailure('source_branch is required', 400);
    return relayRest(
      await proxyRestPost(auth.user, projectRestPath(auth.tenantSlug, projectId, '/merge-requests'), body),
      'mergeRequest',
      201
    );
  } catch (error) {
    return mergeRequestRouteError(error, 'merge requests POST');
  }
}
