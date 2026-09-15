/**
 * Proxy POST for a reviewer's decision — COL-2.2 (#4518).
 *
 * Forwards `{decision, note?}` to apiome-rest's `POST …/reviews/{id}/decision`, which enforces that
 * the caller is a pending reviewer of the current round and that the round can still take
 * decisions. The route checks the body first with the page's own rule — a note is required with
 * **Request changes** — so a hand-built request cannot record a change request without saying why.
 */

import { NextRequest, NextResponse } from 'next/server';
import {
  decisionPayload,
  isRecordableDecision,
  reviewErrorMessage,
  validateDecisionNote,
} from '@lib/review-page';
import { proxyRestPost } from '@lib/primitives-api-proxy';
import {
  isReviewDetail,
  resolveReviewContext,
  restErrorCode,
  reviewFailure,
  reviewRestPath,
  reviewRouteError,
  upstreamStatus,
} from '../../review-proxy';

/**
 * POST /api/reviews/[reviewId]/decision — body `{decision: "approve" | "request_changes", note?}`.
 *
 * @param request - The browser's request.
 * @param context - The route parameters.
 * @returns `{success: true, review}` (the review after the decision) or
 *   `{success: false, error, code?}` — 400 for a malformed body or a missing change-request note,
 *   and apiome-rest's status and `review-*` code for its refusals.
 */
export async function POST(request: NextRequest, { params }: { params: Promise<{ reviewId: string }> }) {
  try {
    const { reviewId } = await params;
    const ctx = await resolveReviewContext(reviewId);
    if (ctx instanceof NextResponse) return ctx;

    let body: unknown;
    try {
      body = await request.json();
    } catch {
      return reviewFailure('The request body must be JSON', 400);
    }
    const { decision, note } = (body ?? {}) as { decision?: unknown; note?: unknown };
    if (!isRecordableDecision(decision)) {
      return reviewFailure('Choose approve or request changes', 400);
    }
    if (note !== undefined && note !== null && typeof note !== 'string') {
      return reviewFailure('The note must be text', 400);
    }
    const text = typeof note === 'string' ? note : '';
    const invalid = validateDecisionNote(decision, text);
    if (invalid) return reviewFailure(invalid, 400);

    const { data, error, status, detail } = await proxyRestPost(
      ctx.user,
      reviewRestPath(ctx, '/decision'),
      decisionPayload(decision, text)
    );
    if (error) {
      const code = restErrorCode(detail);
      return reviewFailure(reviewErrorMessage(code, error), upstreamStatus(status), code);
    }
    if (!isReviewDetail(data)) return reviewFailure('Unexpected reply from the review API', 502);
    return NextResponse.json({ success: true, review: data });
  } catch (error) {
    return reviewRouteError(error, 'review decision POST');
  }
}
