/**
 * Proxy for a review's suggested changes — COL-4.2 (#4526).
 *
 * - `GET`  → `{success, suggestions, canDecide, targets}`: apiome-rest's list, plus the classes and
 *   top-level properties of the reviewed version the **Suggest a change** form can target.
 * - `POST` → `{target_type, target_id, patch, note?}`, forwarded to apiome-rest, which owns every
 *   rule (who may suggest, that the patch applies, that the target is in the version).
 */

import { NextRequest, NextResponse } from 'next/server';
import { proxyRestGet, proxyRestPost } from '@lib/primitives-api-proxy';
import { SUGGESTION_ERROR_MESSAGES, targetsFromClasses, type ReviewSuggestion } from '@lib/review-suggestions';
import {
  fetchReviewDetail,
  resolveReviewContext,
  restErrorCode,
  reviewFailure,
  reviewRestPath,
  reviewRouteError,
  upstreamStatus,
} from '../../review-proxy';

/**
 * GET /api/reviews/[reviewId]/suggestions
 *
 * @param _request - Unused.
 * @param context - The route parameters.
 * @returns The suggestions, whether the caller may decide them, and the version's targets.
 */
export async function GET(_request: NextRequest, { params }: { params: Promise<{ reviewId: string }> }) {
  try {
    const { reviewId } = await params;
    const ctx = await resolveReviewContext(reviewId);
    if (ctx instanceof NextResponse) return ctx;
    const detail = await fetchReviewDetail(ctx);
    if (detail instanceof NextResponse) return detail;

    const [list, classes] = await Promise.all([
      proxyRestGet(ctx.user, reviewRestPath(ctx, '/suggestions')),
      proxyRestGet(
        ctx.user,
        `/classes/${encodeURIComponent(ctx.tenantSlug)}/version/${encodeURIComponent(detail.review.version_id)}/with-properties-tags`
      ),
    ]);
    if (list.error) {
      const code = restErrorCode(list.detail);
      return reviewFailure(SUGGESTION_ERROR_MESSAGES[code ?? ''] ?? list.error, upstreamStatus(list.status), code);
    }
    const body = list.data as { suggestions?: ReviewSuggestion[]; can_decide?: boolean } | null;
    return NextResponse.json({
      success: true,
      suggestions: Array.isArray(body?.suggestions) ? body.suggestions : [],
      canDecide: Boolean(body?.can_decide),
      // The form is a nicety: without the targets the list still works.
      targets: classes.error ? [] : targetsFromClasses(classes.data),
    });
  } catch (error) {
    return reviewRouteError(error, 'review suggestions GET');
  }
}

/**
 * POST /api/reviews/[reviewId]/suggestions — propose a change.
 *
 * @param request - `{target_type, target_id, patch, note?}`.
 * @param context - The route parameters.
 * @returns `{success: true, suggestion}` or `{success: false, error, code?}`.
 */
export async function POST(request: NextRequest, { params }: { params: Promise<{ reviewId: string }> }) {
  try {
    const { reviewId } = await params;
    const ctx = await resolveReviewContext(reviewId);
    if (ctx instanceof NextResponse) return ctx;
    let body: Record<string, unknown>;
    try {
      body = (await request.json()) as Record<string, unknown>;
    } catch {
      return reviewFailure('The request body must be JSON', 400);
    }
    if (!body || (body.target_type !== 'class' && body.target_type !== 'property') || typeof body.target_id !== 'string' || !Array.isArray(body.patch)) {
      return reviewFailure('Choose an element and a change', 400);
    }
    const payload = {
      target_type: body.target_type,
      target_id: body.target_id,
      patch: body.patch,
      ...(typeof body.note === 'string' && body.note.trim() ? { note: body.note } : {}),
    };
    const { data, error, status, detail } = await proxyRestPost(ctx.user, reviewRestPath(ctx, '/suggestions'), payload);
    if (error) {
      const code = restErrorCode(detail);
      return reviewFailure(SUGGESTION_ERROR_MESSAGES[code ?? ''] ?? error, upstreamStatus(status), code);
    }
    return NextResponse.json({ success: true, suggestion: data });
  } catch (error) {
    return reviewRouteError(error, 'review suggestions POST');
  }
}
