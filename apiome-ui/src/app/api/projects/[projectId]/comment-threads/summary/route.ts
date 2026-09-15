/**
 * Proxy GET for a project's comment-thread counts — COL-1.3 (#4515).
 *
 * Two kinds of number, both from apiome-rest so they cannot disagree with the Studio:
 *
 * - **Status totals** for the Discussion panel's chips: one `limit=1` read per status, narrowed by
 *   the same `mentions_me` / `anchor_type` filters as the list, reading apiome-rest's `total`.
 * - **Unresolved per element** for each row, and the unfiltered unresolved total for the tab: the
 *   project's open threads read page by page and counted with `unresolvedCommentCounts` — the
 *   Studio badges' own rule.
 */

import { NextRequest, NextResponse } from 'next/server';
import {
  COMMENT_THREAD_STATUSES,
  sanitizeThreadListParams,
  unresolvedCommentCounts,
  type CommentThreadStatus,
  type DiscussionSummary,
} from '@lib/comment-discussion';
import {
  collectOpenCommentThreads,
  commentThreadsErrorResponse,
  fetchCommentThreadPage,
  resolveCommentThreadsAuth,
} from '../comment-threads-proxy';

/**
 * GET /api/projects/[projectId]/comment-threads/summary?anchor_type&mentions_me
 *
 * @param request - The browser's request; `anchor_type` and `mentions_me` narrow the status totals.
 * @param context - The route parameters.
 * @returns `{success: true, ...DiscussionSummary}` or `{success: false, error}`.
 */
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ projectId: string }> }
) {
  try {
    const { projectId } = await params;
    const auth = await resolveCommentThreadsAuth();
    if (auth instanceof NextResponse) return auth;

    const filters = sanitizeThreadListParams(request.nextUrl.searchParams);

    /**
     * The one-row query that reads a status's total under the current filters.
     *
     * @param status - The status to total.
     * @returns The sanitized REST query.
     */
    const totalQuery = (status: CommentThreadStatus): URLSearchParams => {
      const query = new URLSearchParams({ status, limit: '1', offset: '0' });
      const anchorType = filters.get('anchor_type');
      if (anchorType) query.set('anchor_type', anchorType);
      if (filters.get('mentions_me') === 'true') query.set('mentions_me', 'true');
      return query;
    };

    const [totals, open] = await Promise.all([
      Promise.all(
        COMMENT_THREAD_STATUSES.map(async (status) => {
          const page = await fetchCommentThreadPage(auth, projectId, totalQuery(status));
          return [status, page.total] as const;
        })
      ),
      collectOpenCommentThreads(auth, projectId),
    ]);

    const summary: DiscussionSummary = {
      statusTotals: Object.fromEntries(totals) as Record<CommentThreadStatus, number>,
      unresolvedTotal: open.total,
      unresolvedByAnchor: unresolvedCommentCounts(open.threads),
      truncated: open.total > open.threads.length,
    };
    return NextResponse.json({ success: true, ...summary });
  } catch (error) {
    return commentThreadsErrorResponse(error, 'project comment-threads summary GET');
  }
}
