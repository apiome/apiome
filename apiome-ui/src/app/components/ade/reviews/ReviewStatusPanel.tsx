'use client';

/**
 * The publish dialog's review panel — COL-2.4 (#4520).
 *
 * COL-2.3 put an approval gate in front of publishing and, by design, left it invisible until the
 * button was pressed: the policy is resolved server-side and refuses with a `422`. A publisher who
 * had not been told a review existed met the gate for the first time as an error.
 *
 * This panel is the warning. It sits **above** the three existing gates in the dialog's aside —
 * style guide, breaking changes, verification policy — because it is the one that explains a
 * refusal nothing else on the screen accounts for, and it wears their `.ver-gate` chrome so the
 * column reads as four statements of the same kind.
 *
 * ### What it does and does not claim
 *
 * It reports the **review**, not the policy: where the revision stands, the current round's tally,
 * and a link to the review page. The policy itself (how many approvals, which role) lives in the
 * style guide and is resolved by apiome-rest at publish time, so this panel says what a policy
 * *would* make of the review rather than asserting a verdict it has not been told. Nothing here
 * blocks the Publish button — the four blockers the dialog already derives are unchanged.
 */

import * as React from 'react';
import { ExternalLink, MessageSquareCheck } from 'lucide-react';
import Link from 'next/link';

import {
  REVIEW_STATE_LABEL,
  reviewPageHref,
  reviewTallyText,
  reviewVersionLabel,
  type ReviewStatusRow,
} from '@lib/review-status';

import { ReviewStatusPill } from './ReviewStatusPill';

/**
 * What each state means for a publish that a policy is watching.
 *
 * Phrased conditionally on purpose: whether this workspace requires approvals is a style-guide
 * setting the dialog has not read, so the panel states the review's standing and what an armed
 * policy makes of it, and never promises the publish will or will not go through.
 */
const REVIEW_PUBLISH_NOTE: Readonly<Record<ReviewStatusRow['state'], string>> = {
  in_review:
    'If this workspace requires approvals, publishing is refused until this round has them.',
  approved: 'An approval requirement is satisfied by this round, unless the spec changes again.',
  changes_requested:
    'A workspace that requires approvals refuses this publish until the changes are addressed and the review is re-requested.',
};

export interface ReviewStatusPanelProps {
  /** The revision's open review, or null when it has none. */
  review: ReviewStatusRow | null;
  /** True while the read is in flight — the panel says so rather than claiming "no review". */
  loading?: boolean;
}

/**
 * Draw the panel. See {@link ReviewStatusPanelProps}.
 *
 * @returns The gate-shaped card.
 */
export function ReviewStatusPanel({ review, loading = false }: ReviewStatusPanelProps) {
  return (
    <div className="ver-gate" data-testid="publish-review-panel">
      <div className="ver-gate__head">
        <h3 className="ver-gate__title">
          <MessageSquareCheck aria-hidden />
          Review
        </h3>
        <span className="ver-gate__badges">
          <ReviewStatusPill review={review} data-testid="publish-review-pill" />
        </span>
      </div>

      {/* A review already read wins over a refresh in flight: the rows the refresh will replace
          are still the best answer there is, and blanking the card would flicker. */}
      {review ? (
        <>
          <p className="ver-gate__sub">
            {`${reviewVersionLabel(review)} · round ${review.round} · ${reviewTallyText(review)}`}
          </p>
          <p className="ver-gate__note">{REVIEW_PUBLISH_NOTE[review.state]}</p>
          <p className="ver-gate__sub">
            <Link
              href={reviewPageHref(review.reviewId)}
              className="rvs-link"
              data-testid="publish-review-link"
            >
              {`Open the ${REVIEW_STATE_LABEL[review.state].toLowerCase()} review`}
              <ExternalLink aria-hidden />
            </Link>
          </p>
        </>
      ) : loading ? (
        <p className="ver-gate__note">Checking whether this revision is in review…</p>
      ) : (
        <p className="ver-gate__note" data-testid="publish-review-none">
          No open review. A workspace whose style guide requires approvals refuses this publish
          until one is requested and decided.
        </p>
      )}
    </div>
  );
}

export default ReviewStatusPanel;
