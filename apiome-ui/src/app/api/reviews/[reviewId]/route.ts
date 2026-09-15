/**
 * Proxy GET for one review — COL-2.2 (#4518).
 *
 * Answers the review page's header, reviewers and decision bar: apiome-rest's
 * `GET /v1/tenants/{tenant}/projects/{project}/reviews/{id}`, plus the project's name for the
 * breadcrumb and the signed-in user's id so the page can tell whether they are a reviewer.
 */

import { NextRequest, NextResponse } from 'next/server';
import type { ReviewPagePayload } from '@lib/review-page';
import { fetchReviewDetail, resolveReviewContext, reviewRouteError } from '../review-proxy';

/**
 * GET /api/reviews/[reviewId]
 *
 * @param _request - The browser's request.
 * @param context - The route parameters.
 * @returns `{success: true, review, project, viewerId}` or `{success: false, error, code?}`.
 */
export async function GET(_request: NextRequest, { params }: { params: Promise<{ reviewId: string }> }) {
  try {
    const { reviewId } = await params;
    const ctx = await resolveReviewContext(reviewId);
    if (ctx instanceof NextResponse) return ctx;

    const review = await fetchReviewDetail(ctx);
    if (review instanceof NextResponse) return review;

    const payload: ReviewPagePayload = {
      review,
      project: { id: ctx.project.id, name: ctx.project.name, slug: ctx.project.slug },
      viewerId: ctx.user.user_id ?? null,
    };
    return NextResponse.json({ success: true, ...payload });
  } catch (error) {
    return reviewRouteError(error, 'review GET');
  }
}
