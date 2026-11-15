/**
 * Proxy for deciding a suggested change — COL-4.2 (#4526).
 *
 * `POST /api/reviews/[reviewId]/suggestions/[suggestionId]/apply` and `…/reject` (body
 * `{reason?}`), forwarded to apiome-rest. A stale apply answers 409 `suggestion-stale` with the
 * conflicting paths, which the tab shows.
 */

import { NextRequest, NextResponse } from 'next/server';
import { proxyRestPost } from '@lib/primitives-api-proxy';
import { SUGGESTION_ERROR_MESSAGES } from '@lib/review-suggestions';
import {
  resolveReviewContext,
  restErrorCode,
  reviewFailure,
  reviewRestPath,
  reviewRouteError,
  upstreamStatus,
} from '../../../../review-proxy';

const ACTIONS = new Set(['apply', 'reject']);

/**
 * POST — apply or reject one suggestion.
 *
 * @param request - `{reason?}` for a rejection; ignored for apply.
 * @param context - The route parameters.
 * @returns `{success: true, result}` or `{success: false, error, code?, conflictPaths?}`.
 */
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ reviewId: string; suggestionId: string; action: string }> }
) {
  try {
    const { reviewId, suggestionId, action } = await params;
    if (!ACTIONS.has(action)) return reviewFailure('Unknown action', 404);
    const ctx = await resolveReviewContext(reviewId);
    if (ctx instanceof NextResponse) return ctx;
    const body = (await request.json().catch(() => ({}))) as { reason?: unknown };
    const payload = action === 'reject' && typeof body?.reason === 'string' && body.reason.trim() ? { reason: body.reason } : {};
    const { data, error, status, detail } = await proxyRestPost(
      ctx.user,
      reviewRestPath(ctx, `/suggestions/${encodeURIComponent(suggestionId)}/${action}`),
      payload
    );
    if (error) {
      const code = restErrorCode(detail);
      const conflictPaths = (detail as { conflict_paths?: unknown } | null)?.conflict_paths;
      return NextResponse.json(
        {
          success: false,
          error: SUGGESTION_ERROR_MESSAGES[code ?? ''] ?? error,
          ...(code ? { code } : {}),
          ...(Array.isArray(conflictPaths) ? { conflictPaths } : {}),
        },
        { status: upstreamStatus(status) }
      );
    }
    return NextResponse.json({ success: true, result: data });
  } catch (error) {
    return reviewRouteError(error, 'review suggestion decision POST');
  }
}
