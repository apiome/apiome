'use client';

/**
 * The merge request page's Review tab — COL-4.3 (#4527).
 *
 * Reviewers decide on the **COL-2.1 review of the branch tip**, on the review page — the merge
 * request has no decisions of its own. This tab says where that review stands (its badge, round and
 * tally, and the reviewers' decisions through the review page's own `ReviewReviewers`) and links to
 * the review page, where reviewers approve, request changes, suggest edits and discuss.
 */

import * as React from 'react';
import Link from 'next/link';
import { ExternalLink, MessageSquareCheck } from 'lucide-react';

import { Alert } from '@/app/components/ui/Alert';
import { Badge } from '@/app/components/ui/Badge';
import { EmptyState } from '@/app/components/ui/EmptyState';
import { reviewProgressText, reviewStatusBadge } from '@lib/review-page';
import { reviewPageHref } from '@lib/review-status';
import type { MergeRequestDetail } from '@lib/merge-requests';

import { ReviewReviewers } from '../reviews/ReviewReviewers';

export interface MergeRequestReviewPanelProps {
  detail: MergeRequestDetail;
  /** The signed-in user, whose reviewer row is marked "(you)". */
  viewerId: string | null;
}

/**
 * The Review tab.
 *
 * @param props - See {@link MergeRequestReviewPanelProps}.
 * @returns The panel.
 */
export function MergeRequestReviewPanel({ detail, viewerId }: MergeRequestReviewPanelProps) {
  const review = detail.review;
  if (!review) {
    return (
      <EmptyState
        icon={<MessageSquareCheck />}
        title="No review attached"
        description="Request a review of the current tip from the Status card."
        data-testid="mr-review-none"
      />
    );
  }
  const badge = reviewStatusBadge(review.review);
  return (
    <section className="mrq-review" aria-label="Review" data-testid="mr-review">
      <div className="mrq-review__head">
        <Badge variant={badge.variant} data-testid="mr-review-status">
          {badge.label}
        </Badge>
        <span className="mrq-review__tally">
          Round {review.review.round} · {reviewProgressText(review.review)}
        </span>
        <Link className="mrq-review__link" href={reviewPageHref(review.review.id)} data-testid="mr-review-link">
          Open the review
          <ExternalLink aria-hidden className="mrq-review__glyph" />
        </Link>
      </div>
      {detail.review_outdated ? (
        <Alert variant="warn" data-testid="mr-review-outdated">
          This review judged an earlier tip of {detail.merge_request.source_branch_name}. Request a review of the
          current tip before merging.
        </Alert>
      ) : review.spec_changed && !review.review.closed_at ? (
        <Alert variant="warn" data-testid="mr-review-stale">
          The branch changed after round {review.review.round} was requested. Re-request the review on the review page.
        </Alert>
      ) : null}
      <ReviewReviewers detail={review} viewerId={viewerId} />
    </section>
  );
}
