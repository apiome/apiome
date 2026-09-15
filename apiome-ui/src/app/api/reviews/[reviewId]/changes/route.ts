/**
 * Proxy GET for a review's Changes tab — COL-2.2 (#4518).
 *
 * Compares the version under review with the project's **newest published version**
 * (`newestPublishedRevision`) through CTG-1.2/1.3's live classifier,
 * `POST /v1/diff/{tenant}/classified`. The version under review is always a draft (COL-2.1 refuses
 * to review published versions), so the stored publish-time changelogs cannot answer this — the
 * classification is computed on request.
 *
 * - Nothing published yet → `initialPublication: true` and no changes.
 * - Classification fails (or is refused) → `classifiedError` with the reason; the tab falls back to
 *   the plain diff of the two documents, which `GET …/spec?side=base|head` serves.
 */

import { NextRequest, NextResponse } from 'next/server';
import { proxyRestPost } from '@lib/primitives-api-proxy';
import {
  newestPublishedRevision,
  sameId,
  type ClassifiedChange,
  type ReviewChangesPayload,
} from '@lib/review-page';
import type { ChangelogSeverity } from '@lib/version-changelog';
import {
  fetchProjectRevisions,
  fetchReviewDetail,
  resolveReviewContext,
  reviewRouteError,
} from '../../review-proxy';

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
 * GET /api/reviews/[reviewId]/changes
 *
 * @param _request - The browser's request.
 * @param context - The route parameters.
 * @returns `{success: true, ...ReviewChangesPayload}` or `{success: false, error, code?}`.
 */
export async function GET(_request: NextRequest, { params }: { params: Promise<{ reviewId: string }> }) {
  try {
    const { reviewId } = await params;
    const ctx = await resolveReviewContext(reviewId);
    if (ctx instanceof NextResponse) return ctx;

    const review = await fetchReviewDetail(ctx);
    if (review instanceof NextResponse) return review;
    const revisions = await fetchProjectRevisions(ctx);
    if (revisions instanceof NextResponse) return revisions;

    const headId = review.review.version_id;
    const head = {
      id: headId,
      label:
        review.review.version_label ?? revisions.find((row) => sameId(row.id, headId))?.version_id ?? null,
    };
    const baselineRow = newestPublishedRevision(revisions, headId);
    const empty: Omit<ReviewChangesPayload, 'head' | 'baseline' | 'initialPublication'> = {
      changes: [],
      counts: {},
      maxSeverity: null,
      classifiedError: null,
    };

    if (!baselineRow) {
      const payload: ReviewChangesPayload = { head, baseline: null, initialPublication: true, ...empty };
      return NextResponse.json({ success: true, ...payload });
    }

    const baseline = { id: baselineRow.id, label: baselineRow.version_id };
    const { data, error } = await proxyRestPost(
      ctx.user,
      `/diff/${encodeURIComponent(ctx.tenantSlug)}/classified`,
      {
        base: { project: ctx.project.id, version: baseline.id },
        head: { project: ctx.project.id, version: headId },
      }
    );

    const payload: ReviewChangesPayload =
      error || !isClassifiedDiff(data)
        ? {
            head,
            baseline,
            initialPublication: false,
            ...empty,
            classifiedError: error || 'Unexpected reply from the diff API',
          }
        : {
            head,
            baseline,
            initialPublication: false,
            changes: data.changes,
            counts: data.counts ?? {},
            maxSeverity: data.maxSeverity ?? null,
            classifiedError: null,
          };
    return NextResponse.json({ success: true, ...payload });
  } catch (error) {
    return reviewRouteError(error, 'review changes GET');
  }
}
