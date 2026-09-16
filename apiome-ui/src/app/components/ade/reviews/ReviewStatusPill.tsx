'use client';

/**
 * The review status pill — COL-2.4 (#4520).
 *
 * One component for every surface the ticket names: version rows, project cards, the projects
 * table and the publish dialog. It draws the shared `Badge` with the review's state as its
 * vocabulary string — so the tone comes from `statusVocabulary.ts`, not from whichever screen is
 * drawing it — wrapped in the link to `/ade/reviews/{id}` that the ticket's second acceptance
 * criterion asks for.
 *
 * ### Colour is never the only signal
 *
 * The badge says the state in words, and the link's accessible name
 * ({@link reviewPillTitle}) names the revision as well, because "In review" on a project card
 * does not say *what* is in review. A card standing for several open reviews adds a `+N` chip
 * rather than a second colour.
 *
 * ### It renders nothing when there is nothing to say
 *
 * A revision with no open review is a draft — COL-2.1 does not store that as a state — and a
 * draft already carries the `Draft` lifecycle badge beside this one. A second pill reading "Not in
 * review" would be furniture.
 *
 * ### It keeps its click to itself
 *
 * On the projects table the pill lives inside a `DataTable` row whose own activation opens the
 * project's revisions. `DataTable` only stops propagation for the selection checkbox and the
 * actions column, so without the two handlers below a click on the pill would start *two*
 * navigations — and `Enter` would be worse, because the row's key handler calls
 * `preventDefault()` and would cancel the link outright. Both are stopped here rather than in the
 * table, because it is this pill that knows its destination is not the row's.
 */

import * as React from 'react';
import Link from 'next/link';

import { Badge } from '@/app/components/ui/Badge';
import {
  REVIEW_STATE_LABEL,
  reviewPageHref,
  reviewPillTitle,
  type ReviewStatusRow,
} from '@lib/review-status';
import { cn } from '@lib/utils';

export interface ReviewStatusPillProps {
  /** The open review, or null/undefined to draw nothing. */
  review: ReviewStatusRow | null | undefined;
  /**
   * Further open reviews this pill stands for, on a surface with room for only one (a project
   * card or table row). Drawn as a `+N` chip. Default `0`.
   */
  moreCount?: number;
  /** Extra classes for the surface to place the pill with. */
  className?: string;
  /** Test hook; the surface names itself so three pills on one screen stay distinguishable. */
  'data-testid'?: string;
}

/**
 * Draw the pill. See {@link ReviewStatusPillProps}.
 *
 * @returns The linked badge, or `null` when there is no open review.
 */
export function ReviewStatusPill({
  review,
  moreCount = 0,
  className,
  'data-testid': testId,
}: ReviewStatusPillProps) {
  if (!review) return null;
  const more = Math.max(0, Math.trunc(moreCount));
  const title = reviewPillTitle(review, more);

  return (
    <Link
      href={reviewPageHref(review.reviewId)}
      className={cn('rvs-pill', className)}
      title={title}
      aria-label={title}
      data-review-state={review.state}
      data-testid={testId ?? 'review-status-pill'}
      onClick={(event) => event.stopPropagation()}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') event.stopPropagation();
      }}
    >
      <Badge status={review.state} dot>
        {REVIEW_STATE_LABEL[review.state]}
      </Badge>
      {more > 0 ? (
        <Badge variant="secondary" data-testid="review-status-pill-more">
          {`+${more}`}
        </Badge>
      ) : null}
    </Link>
  );
}

export default ReviewStatusPill;
