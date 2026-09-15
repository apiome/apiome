/**
 * Proxy GET for a project's comment threads — COL-1.3 (#4515).
 *
 * Forwards the Discussion panel's filters to apiome-rest's
 * `GET /v1/tenants/{tenant}/projects/{project}/comment-threads` (every version of the project,
 * newest activity first), then adds each thread's `anchor_context` — the element's name, plus the
 * class name or pathname its Studio deep link needs — which the REST row does not carry.
 */

import { NextRequest, NextResponse } from 'next/server';
import { commentAnchorKey, sanitizeThreadListParams } from '@lib/comment-discussion';
import { resolveCommentAnchorContexts } from '@lib/db/comment-anchor-labels';
import {
  commentThreadsErrorResponse,
  fetchCommentThreadPage,
  resolveCommentThreadsAuth,
} from './comment-threads-proxy';

/**
 * GET /api/projects/[projectId]/comment-threads?status&anchor_type&mentions_me&limit&offset
 *
 * @param request - The browser's request; only the whitelisted filters are forwarded.
 * @param context - The route parameters.
 * @returns `{success: true, threads, count, total, limit, offset}`, each thread with
 *   `anchor_context` (null when it could not be resolved), or `{success: false, error}`.
 */
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ projectId: string }> }
) {
  try {
    const { projectId } = await params;
    const auth = await resolveCommentThreadsAuth();
    if (auth instanceof NextResponse) return auth;

    const page = await fetchCommentThreadPage(
      auth,
      projectId,
      sanitizeThreadListParams(request.nextUrl.searchParams)
    );

    // Labels are a nicety on top of rows REST already authorized: a failure here costs the names
    // and the canvas focus, never the list.
    let contexts = new Map();
    try {
      contexts = await resolveCommentAnchorContexts(
        { tenantId: auth.tenantId, projectRef: projectId },
        page.threads
      );
    } catch (error) {
      console.error('comment-threads anchor labels:', error);
    }

    const threads = page.threads.map((thread) => ({
      ...thread,
      anchor_context: contexts.get(commentAnchorKey(thread.anchor_type, thread.anchor_id)) ?? null,
    }));
    return NextResponse.json({ success: true, ...page, threads });
  } catch (error) {
    return commentThreadsErrorResponse(error, 'project comment-threads GET');
  }
}
