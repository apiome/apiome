/**
 * One merge request, for its page — COL-4.3 (#4527).
 *
 * GET /api/merge-requests/[mergeRequestId] → `{success, mergeRequest, project, viewerId}`
 *
 * Reads the merge request from apiome-rest (which enforces `versions:view`) and adds the project
 * for the breadcrumb and the viewer's id for the review panel.
 */

import { NextRequest, NextResponse } from 'next/server';
import {
  fetchMergeRequestDetail,
  mergeRequestRouteError,
  resolveMergeRequestContext,
} from '../merge-request-proxy';

/**
 * Read the merge request.
 *
 * @param _request - The browser's request.
 * @param context - The route parameters.
 * @returns The page payload, or a failure envelope.
 */
export async function GET(_request: NextRequest, { params }: { params: Promise<{ mergeRequestId: string }> }) {
  try {
    const { mergeRequestId } = await params;
    const ctx = await resolveMergeRequestContext(mergeRequestId);
    if (ctx instanceof NextResponse) return ctx;
    const detail = await fetchMergeRequestDetail(ctx);
    if (detail instanceof NextResponse) return detail;
    return NextResponse.json({
      success: true,
      mergeRequest: detail,
      project: { id: ctx.project.id, name: ctx.project.name, slug: ctx.project.slug },
      viewerId: ctx.user.user_id ?? null,
    });
  } catch (error) {
    return mergeRequestRouteError(error, 'merge request GET');
  }
}
