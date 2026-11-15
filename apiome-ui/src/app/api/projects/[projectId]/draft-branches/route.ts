/**
 * Draft branches of a project — COL-4.3 (#4527).
 *
 * GET  /api/projects/[projectId]/draft-branches → `{success, branches}`
 * POST /api/projects/[projectId]/draft-branches — body `{name, base_branch, version_label?}` →
 *   `{success, branch}` (201)
 *
 * Proxies `…/v1/tenants/{tenant}/projects/{project}/draft-branches`, which enforces
 * `versions:view` / `versions:create` and copies the line's tip into the branch's own revision.
 */

import { NextRequest } from 'next/server';
import { getAuthenticatedTenantContext, proxyRestGet, proxyRestPost } from '@lib/primitives-api-proxy';
import { reviewFailure } from '../../../reviews/review-proxy';
import { mergeRequestRouteError, projectRestPath, relayRest } from '../../../merge-requests/merge-request-proxy';

type Params = { params: Promise<{ projectId: string }> };

/**
 * List the project's draft branches.
 *
 * @param _request - The browser's request.
 * @param context - The route parameters.
 * @returns `{success: true, branches}` or a failure envelope.
 */
export async function GET(_request: NextRequest, { params }: Params) {
  try {
    const auth = await getAuthenticatedTenantContext();
    if (!auth.ok) return reviewFailure(auth.error, auth.status);
    const { projectId } = await params;
    return relayRest(await proxyRestGet(auth.user, projectRestPath(auth.tenantSlug, projectId, '/draft-branches')));
  } catch (error) {
    return mergeRequestRouteError(error, 'draft branches GET');
  }
}

/**
 * Create a draft branch off a version line.
 *
 * @param request - The browser's request, carrying the form.
 * @param context - The route parameters.
 * @returns `{success: true, branch}` (201) or a failure envelope.
 */
export async function POST(request: NextRequest, { params }: Params) {
  try {
    const auth = await getAuthenticatedTenantContext();
    if (!auth.ok) return reviewFailure(auth.error, auth.status);
    const { projectId } = await params;
    const body = (await request.json().catch(() => null)) as Record<string, unknown> | null;
    if (!body || typeof body.name !== 'string') return reviewFailure('name is required', 400);
    return relayRest(
      await proxyRestPost(auth.user, projectRestPath(auth.tenantSlug, projectId, '/draft-branches'), body),
      'branch',
      201
    );
  } catch (error) {
    return mergeRequestRouteError(error, 'draft branches POST');
  }
}
