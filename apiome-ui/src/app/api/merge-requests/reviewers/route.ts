/**
 * Who can be asked to review a merge request — COL-4.3 (#4527).
 *
 * GET /api/merge-requests/reviewers → `{success, reviewers: [{user_id, name, email}]}`
 *
 * The caller's tenant's active and pending members, without the caller (`listReviewerCandidates`).
 * The tenant comes from the session, never the browser; apiome-rest re-validates the chosen
 * reviewers when the review is requested.
 */

import { NextResponse } from 'next/server';
import { getAuthenticatedTenantContext } from '@lib/primitives-api-proxy';
import { listReviewerCandidates } from '@lib/db/merge-request-project';
import { reviewFailure } from '../../reviews/review-proxy';
import { mergeRequestRouteError } from '../merge-request-proxy';

/**
 * List the reviewer candidates.
 *
 * @returns `{success: true, reviewers}` or a failure envelope.
 */
export async function GET() {
  try {
    const auth = await getAuthenticatedTenantContext();
    if (!auth.ok) return reviewFailure(auth.error, auth.status);
    const reviewers = await listReviewerCandidates(auth.user.current_tenant_id as string, auth.user.user_id ?? null);
    return NextResponse.json({ success: true, reviewers });
  } catch (error) {
    return mergeRequestRouteError(error, 'merge request reviewers GET');
  }
}
