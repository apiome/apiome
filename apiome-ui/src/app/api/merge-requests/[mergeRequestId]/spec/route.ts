/**
 * Proxy GET for a merge request's OpenAPI documents — COL-4.3 (#4527).
 *
 * `?side=head` (the default) is the branch tip; `?side=base` is the merge base it is compared with,
 * for the Changes tab's plain diff. Both are drafts or published revisions of the project; the
 * document is built exactly as the review page builds it (`buildOpenApiSpecJsonForVersion`). The
 * revision ids come only from the merge request apiome-rest returned — read first, which proves
 * `versions:view` — so no document is built for a revision the caller could not see.
 */

import { NextRequest, NextResponse } from 'next/server';
import { buildOpenApiSpecJsonForVersion } from '@lib/db/helper';
import { coerceProjectMetadataRecord } from '@lib/project-metadata';
import { reviewSpecSideFromQuery } from '@lib/review-page';
import { reviewFailure } from '../../../reviews/review-proxy';
import {
  fetchMergeRequestDetail,
  mergeRequestRouteError,
  resolveMergeRequestContext,
} from '../../merge-request-proxy';

/**
 * GET /api/merge-requests/[mergeRequestId]/spec?side=head|base
 *
 * @param request - The browser's request.
 * @param context - The route parameters.
 * @returns `{success: true, side, versionId, versionLabel, spec}` or a failure envelope.
 */
export async function GET(request: NextRequest, { params }: { params: Promise<{ mergeRequestId: string }> }) {
  try {
    const { mergeRequestId } = await params;
    const side = reviewSpecSideFromQuery(request.nextUrl.searchParams.get('side'));
    const ctx = await resolveMergeRequestContext(mergeRequestId);
    if (ctx instanceof NextResponse) return ctx;
    const detail = await fetchMergeRequestDetail(ctx);
    if (detail instanceof NextResponse) return detail;

    const id = side === 'head' ? detail.source_tip_revision_id : detail.merge_base_revision_id;
    const label = side === 'head' ? detail.source_tip_version_label : detail.merge_base_version_label;
    if (!id) {
      return reviewFailure(
        side === 'head' ? 'The draft branch no longer exists.' : 'The branch and the line share no history.',
        404
      );
    }
    const spec = await buildOpenApiSpecJsonForVersion(
      { id, version_id: label ?? '', shortMessage: null, project_id: ctx.project.id },
      ctx.project.name || null,
      coerceProjectMetadataRecord(ctx.project.metadata)
    );
    return NextResponse.json({ success: true, side, versionId: id, versionLabel: label, spec });
  } catch (error) {
    return mergeRequestRouteError(error, 'merge request spec GET');
  }
}
