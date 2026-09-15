/**
 * Proxy GET for a review's OpenAPI documents — COL-2.2 (#4518).
 *
 * `?side=head` (the default) is the version under review, for the Spec tab; `?side=base` is the
 * newest published version it is compared with, for the Changes tab's plain diff.
 *
 * The public schema endpoint refuses drafts, so the document is built exactly as the Versions
 * screen's spec viewer builds it (`buildOpenApiSpecJsonForVersion`, with the project's name and
 * metadata). The revision is taken only from apiome-rest's version list for the review's project —
 * read after the review itself — so the caller's `projects:view` and `versions:view` are both proven
 * before any document is built.
 */

import { NextRequest, NextResponse } from 'next/server';
import { buildOpenApiSpecJsonForVersion } from '@lib/db/helper';
import { coerceProjectMetadataRecord } from '@lib/project-metadata';
import { newestPublishedRevision, reviewSpecSideFromQuery, sameId } from '@lib/review-page';
import {
  fetchProjectRevisions,
  fetchReviewDetail,
  resolveReviewContext,
  reviewFailure,
  reviewRouteError,
} from '../../review-proxy';

/**
 * GET /api/reviews/[reviewId]/spec?side=head|base
 *
 * @param request - The browser's request.
 * @param context - The route parameters.
 * @returns `{success: true, side, versionId, versionLabel, spec}` (the document as JSON text), or
 *   `{success: false, error, code?}` — 404 when `side=base` and nothing is published.
 */
export async function GET(request: NextRequest, { params }: { params: Promise<{ reviewId: string }> }) {
  try {
    const { reviewId } = await params;
    const side = reviewSpecSideFromQuery(request.nextUrl.searchParams.get('side'));
    const ctx = await resolveReviewContext(reviewId);
    if (ctx instanceof NextResponse) return ctx;

    const review = await fetchReviewDetail(ctx);
    if (review instanceof NextResponse) return review;
    const revisions = await fetchProjectRevisions(ctx);
    if (revisions instanceof NextResponse) return revisions;

    const headId = review.review.version_id;
    const row =
      side === 'head'
        ? revisions.find((candidate) => sameId(candidate.id, headId)) ?? null
        : newestPublishedRevision(revisions, headId);
    if (!row) {
      return reviewFailure(
        side === 'base'
          ? 'Nothing is published in this project yet, so there is no version to compare with.'
          : 'The version under review no longer exists.',
        404
      );
    }

    const spec = await buildOpenApiSpecJsonForVersion(
      {
        id: row.id,
        version_id: row.version_id,
        shortMessage: row.shortMessage ?? null,
        project_id: ctx.project.id,
      },
      ctx.project.name || null,
      coerceProjectMetadataRecord(ctx.project.metadata)
    );
    return NextResponse.json({ success: true, side, versionId: row.id, versionLabel: row.version_id, spec });
  } catch (error) {
    return reviewRouteError(error, 'review spec GET');
  }
}
