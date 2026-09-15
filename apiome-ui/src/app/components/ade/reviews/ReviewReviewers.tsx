'use client';

/**
 * The review page's reviewers card — COL-2.2 (#4518).
 *
 * The current round's reviewers with their decisions and notes, then every earlier round as it was
 * recorded. Decisions are immutable history in apiome-rest (COL-2.1), and this card shows them that
 * way: a re-request adds a round on top, it never rewrites one. A reviewer who had not decided
 * before a re-request keeps a "Pending" row in that earlier round.
 */

import * as React from 'react';

import { Badge } from '@/app/components/ui/Badge';
import { formatRelativeWhen } from '@/app/components/ade/repositories/repositoryDetailModel';
import {
  DECISION_LABELS,
  decisionBadgeVariant,
  sameId,
  type ReviewDetail,
  type ReviewerDecisionRow,
} from '@lib/review-page';

export interface ReviewReviewersProps {
  /** The review. */
  detail: ReviewDetail;
  /** The signed-in user, whose row is marked "(you)". */
  viewerId: string | null;
  /** Reference time for relative dates, in epoch ms; tests pin it. Defaults to mount time. */
  now?: number;
}

/**
 * One reviewer's row.
 *
 * @param props.row - The reviewer row.
 * @param props.viewerId - The signed-in user.
 * @param props.now - Reference time for the relative date.
 * @returns The list item.
 */
function ReviewerItem({ row, viewerId, now }: { row: ReviewerDecisionRow; viewerId: string | null; now: number }) {
  return (
    <li className="rvw-person" data-testid={`review-reviewer-${row.id}`} data-decision={row.decision}>
      <div className="rvw-person__head">
        <span className="rvw-person__name">
          {row.user_name || 'Former member'}
          {sameId(row.user_id, viewerId) ? <span className="rvw-person__you"> (you)</span> : null}
        </span>
        <Badge variant={decisionBadgeVariant(row.decision)}>{DECISION_LABELS[row.decision]}</Badge>
      </div>
      {row.decided_at ? (
        <time className="rvw-person__when" dateTime={row.decided_at} title={row.decided_at}>
          Decided {formatRelativeWhen(row.decided_at, now)}
        </time>
      ) : null}
      {row.note ? <div className="rvw-person__note">{row.note}</div> : null}
    </li>
  );
}

/**
 * Group earlier rounds' rows by round, keeping the order they arrived in (oldest round first).
 *
 * @param rows - The history rows.
 * @returns `[round, rows]` pairs.
 */
function groupByRound(rows: readonly ReviewerDecisionRow[]): Array<[number, ReviewerDecisionRow[]]> {
  const rounds = new Map<number, ReviewerDecisionRow[]>();
  for (const row of rows) {
    const bucket = rounds.get(row.round);
    if (bucket) bucket.push(row);
    else rounds.set(row.round, [row]);
  }
  return [...rounds.entries()];
}

/**
 * The reviewers card.
 *
 * @param props - See {@link ReviewReviewersProps}.
 * @returns The card.
 */
export function ReviewReviewers({ detail, viewerId, now }: ReviewReviewersProps) {
  const titleId = React.useId();
  const [mountedAt] = React.useState(() => Date.now());
  const reference = now ?? mountedAt;
  const rounds = groupByRound(detail.history);

  return (
    <section className="rvw-card" aria-labelledby={titleId} data-testid="review-reviewers">
      <div className="rvw-card__head">
        <h2 className="rvw-card__title" id={titleId}>
          Reviewers
        </h2>
        <span className="rvw-card__meta">Round {detail.review.round}</span>
      </div>
      {detail.reviewers.length ? (
        <ul className="rvw-people">
          {detail.reviewers.map((row) => (
            <ReviewerItem key={row.id} row={row} viewerId={viewerId} now={reference} />
          ))}
        </ul>
      ) : (
        <div className="rvw-card__empty">No reviewers in this round.</div>
      )}
      {rounds.length ? (
        <div className="rvw-history" data-testid="review-history">
          <h3 className="rvw-card__subtitle">Earlier rounds</h3>
          {rounds.map(([round, rows]) => (
            <div key={round} className="rvw-round" data-testid={`review-round-${round}`}>
              <div className="rvw-round__label">Round {round}</div>
              <ul className="rvw-people">
                {rows.map((row) => (
                  <ReviewerItem key={row.id} row={row} viewerId={viewerId} now={reference} />
                ))}
              </ul>
            </div>
          ))}
        </div>
      ) : null}
    </section>
  );
}
