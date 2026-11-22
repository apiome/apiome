/**
 * Proxy GET for a merge request's OpenAPI documents — COL-4.3 (#4527).
 *
 * `?side=head` (the default) is the branch tip; `?side=base` is the merge base it is compared with,
 * for the Changes tab's plain diff. Both are drafts or published revisions of the project.
 *
 * The document is the one apiome-rest renders once and keeps in the document store
 * (`GET /v1/versions/{tenant}/{project}/{version}/document`, COA-5.13 #7089); nothing is generated
 * here. The revision ids come only from the merge request apiome-rest returned, and REST checks
 * `versions:view` again when it serves the document. `sha256` is the document's digest: equal on
 * both sides means the two documents are the same and no diff is needed.
 */

import { NextRequest, NextResponse } from 'next/server';
import { fetchRevisionDocument } from '@lib/revision-document-server';
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
 * @returns `{success: true, side, versionId, versionLabel, spec, sha256}` or a failure envelope.
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
    const document = await fetchRevisionDocument(ctx, ctx.project.id, id);
    if (!document.ok) return reviewFailure(document.error, document.status, document.code);
    return NextResponse.json({
      success: true,
      side,
      versionId: id,
      versionLabel: label,
      spec: document.spec,
      sha256: document.sha256,
    });
  } catch (error) {
    return mergeRequestRouteError(error, 'merge request spec GET');
  }
}
