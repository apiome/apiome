/**
 * Proxy GET for a merge request's Changes tab — COL-4.3 (#4527).
 *
 * What the branch changes: the **merge base** (the common ancestor of the branch and the line)
 * against the **branch tip**, classified by CTG-1.x's live classifier,
 * `POST /v1/diff/{tenant}/classified`. Comparing with the merge base rather than the line's tip
 * shows only the branch's own changes, not everything the line gained since.
 *
 * The reply has the review page's `ReviewChangesPayload` shape, so the tab is the review page's
 * Changes panel pointed at this route. When classification fails, `classifiedError` says why and
 * the tab falls back to the plain diff, which `GET …/spec?side=base|head` serves.
 */

import { NextRequest, NextResponse } from 'next/server';
import { proxyRestPost } from '@lib/primitives-api-proxy';
import type { ClassifiedChange, ReviewChangesPayload } from '@lib/review-page';
import type { ChangelogSeverity } from '@lib/version-changelog';
import { reviewFailure } from '../../../reviews/review-proxy';
import {
  fetchMergeRequestDetail,
  mergeRequestRouteError,
  resolveMergeRequestContext,
} from '../../merge-request-proxy';

/** The part of the classifier's reply the tab reads. */
interface ClassifiedDiffReply {
  changes: ClassifiedChange[];
  counts?: Record<string, number>;
  maxSeverity?: ChangelogSeverity | null;
}

/**
 * Whether a parsed reply is a classified diff.
 *
 * @param value - The reply.
 * @returns True when it has a `changes` array.
 */
function isClassifiedDiff(value: unknown): value is ClassifiedDiffReply {
  return Array.isArray((value as Partial<ClassifiedDiffReply> | null)?.changes);
}

/**
 * GET /api/merge-requests/[mergeRequestId]/changes
 *
 * @param _request - The browser's request.
 * @param context - The route parameters.
 * @returns `{success: true, ...ReviewChangesPayload}` or a failure envelope.
 */
export async function GET(_request: NextRequest, { params }: { params: Promise<{ mergeRequestId: string }> }) {
  try {
    const { mergeRequestId } = await params;
    const ctx = await resolveMergeRequestContext(mergeRequestId);
    if (ctx instanceof NextResponse) return ctx;
    const detail = await fetchMergeRequestDetail(ctx);
    if (detail instanceof NextResponse) return detail;

    if (!detail.source_tip_revision_id) return reviewFailure('The draft branch no longer exists.', 404);
    const head = { id: detail.source_tip_revision_id, label: detail.source_tip_version_label };
    if (!detail.merge_base_revision_id) {
      return reviewFailure('The branch and the line share no history, so there is nothing to compare with.', 409);
    }
    const baseline = { id: detail.merge_base_revision_id, label: detail.merge_base_version_label };

    const { data, error } = await proxyRestPost(
      ctx.user,
      `/diff/${encodeURIComponent(ctx.tenantSlug)}/classified`,
      {
        base: { project: ctx.project.id, version: baseline.id },
        head: { project: ctx.project.id, version: head.id },
      }
    );
    const classified = !error && isClassifiedDiff(data) ? data : null;
    const payload: ReviewChangesPayload = {
      head,
      baseline,
      initialPublication: false,
      changes: classified?.changes ?? [],
      counts: classified?.counts ?? {},
      maxSeverity: classified?.maxSeverity ?? null,
      classifiedError: classified ? null : error || 'Unexpected reply from the diff API',
    };
    return NextResponse.json({ success: true, ...payload });
  } catch (error) {
    return mergeRequestRouteError(error, 'merge request changes GET');
  }
}
