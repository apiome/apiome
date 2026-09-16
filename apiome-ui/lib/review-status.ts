/**
 * Review status surfaces — COL-2.4 (#4520).
 *
 * COL-2.1 gave a draft version a review record and COL-2.2 gave it a page, but nothing in the
 * product linked to either: you had to already know a review existed to go and look at it. So
 * approvals stalled, and the COL-2.3 publish gate arrived as a 422 nobody saw coming.
 *
 * This module is the rule set behind the pill that fixes that — `In review` / `Approved` /
 * `Changes requested`, on version rows, project cards and the publish dialog, each one a link to
 * `/ade/reviews/{id}`. It is framework- and database-free so the BFF route, the pill component,
 * the three screens and the tests all agree on:
 *
 * - {@link ReviewStatusRow}, the shape `GET /api/reviews/status` answers with;
 * - {@link REVIEW_STATE_LABEL} and {@link reviewPageHref}, the pill's two halves;
 * - {@link indexReviewsByVersion}, the map a version row looks itself up in;
 * - {@link summarizeProjectReviews}, which collapses a project's open reviews into the single
 *   pill a card or a table row has room for — the most urgent one, plus how many are behind it;
 * - {@link reviewTallyText} and {@link reviewPillTitle}, the sentences that keep the colour from
 *   being the only signal.
 *
 * The one thing it does **not** hold is which reviews exist: that is a read, and it lives in
 * `lib/db/review-status.ts` behind the session's tenant.
 */

import { reviewProgressText, type ReviewState } from './review-page';

export type { ReviewState };

/* -------------------------------------------------------------------------- */
/* The wire row                                                               */
/* -------------------------------------------------------------------------- */

/**
 * One **open** review, as every status surface needs it.
 *
 * Deliberately smaller than COL-2.2's `ReviewDetail`: a pill needs the state, the tally and
 * enough identity to link and to name itself. Withdrawn reviews never appear — a withdrawn
 * review is not a status, it is the absence of one — so there is no `closedAt` to check.
 */
export interface ReviewStatusRow {
  /** The review, which is also the `/ade/reviews/{id}` segment. */
  reviewId: string;
  /** The project the reviewed revision belongs to. */
  projectId: string;
  /** The revision under review (`versions.id`, a UUID). */
  versionId: string;
  /** Its label, e.g. `1.2.0`; null when the revision carries none. */
  versionLabel: string | null;
  /** Where the review stands. */
  state: ReviewState;
  /** The current round; each re-request starts the next. */
  round: number;
  /** Reviewers asked in the current round. */
  reviewerCount: number;
  /** How many of them approved. */
  approvedCount: number;
  /** How many requested changes. */
  changesRequestedCount: number;
  /** How many have not decided yet. */
  pendingCount: number;
  /** Last request, re-request or decision, as an ISO instant. */
  updatedAt: string;
}

/* -------------------------------------------------------------------------- */
/* The pill                                                                   */
/* -------------------------------------------------------------------------- */

/**
 * Each state, in the words the ticket spells.
 *
 * The strings are also the `Badge` `status` values, so the tone comes from the shared status
 * vocabulary (`statusVocabulary.ts`) rather than from any screen — a review reads the same amber
 * on a version row as on a project card as in the publish dialog.
 */
export const REVIEW_STATE_LABEL: Readonly<Record<ReviewState, string>> = {
  in_review: 'In review',
  approved: 'Approved',
  changes_requested: 'Changes requested',
};

/**
 * How urgent each state is, highest first.
 *
 * A project card has room for one pill and a project may have several open reviews, so one of
 * them has to speak for the rest. Changes requested outranks everything — somebody is waiting on
 * the author; in review outranks approved, because a decision is still owed; approved is last,
 * being the state that needs nobody.
 */
export const REVIEW_STATE_URGENCY: Readonly<Record<ReviewState, number>> = {
  changes_requested: 2,
  in_review: 1,
  approved: 0,
};

/**
 * The review page's route.
 *
 * @param reviewId - The review.
 * @returns `/ade/reviews/{id}`, with the id encoded.
 */
export function reviewPageHref(reviewId: string): string {
  return `/ade/reviews/${encodeURIComponent(reviewId)}`;
}

/**
 * The revision, as a pill names it.
 *
 * @param review - The review.
 * @returns `v1.2.0`, or the short revision id when the revision carries no label.
 */
export function reviewVersionLabel(review: Pick<ReviewStatusRow, 'versionLabel' | 'versionId'>): string {
  const label = review.versionLabel?.trim();
  if (label) return `v${label}`;
  return review.versionId.slice(0, 8);
}

/**
 * The current round's tally, in words: `1 of 2 approved · 1 pending`.
 *
 * Delegates to COL-2.2's {@link reviewProgressText} so the dialog's line and the review page's
 * header can never word the same tally differently.
 *
 * @param review - The review.
 * @returns The sentence.
 */
export function reviewTallyText(review: ReviewStatusRow): string {
  return reviewProgressText({
    reviewer_count: review.reviewerCount,
    approved_count: review.approvedCount,
    changes_requested_count: review.changesRequestedCount,
    pending_count: review.pendingCount,
  });
}

/**
 * The pill's `title` — and, with the state prepended, its accessible name.
 *
 * DESIGN.md §6 forbids colour as the only signal, and "In review" alone does not say *what* is
 * in review when the pill sits on a project card. This says both, and what clicking does.
 *
 * @param review - The review.
 * @param moreCount - How many further open reviews the pill stands for. Default `0`.
 * @returns One sentence.
 */
export function reviewPillTitle(review: ReviewStatusRow, moreCount = 0): string {
  const subject = `${reviewVersionLabel(review)} — ${REVIEW_STATE_LABEL[review.state].toLowerCase()}`;
  const rest =
    moreCount > 0
      ? ` · ${moreCount} more open ${moreCount === 1 ? 'review' : 'reviews'} in this project`
      : '';
  return `${subject}${rest} · open the review`;
}

/* -------------------------------------------------------------------------- */
/* Indexing                                                                   */
/* -------------------------------------------------------------------------- */

/**
 * Compare two ids the way the rest of the app does: trimmed and case-insensitively.
 *
 * @param value - An id.
 * @returns Its map key, or null when there is nothing to key on.
 */
function idKey(value: string | null | undefined): string | null {
  const trimmed = value?.trim().toLowerCase();
  return trimmed ? trimmed : null;
}

/**
 * The open review of each revision.
 *
 * COL-2.1's partial unique index allows only one open review per version, so a later row can only
 * mean the two disagree; the **most recently updated** wins, which is the one a reader would have
 * acted on last.
 *
 * @param reviews - Open reviews, in any order.
 * @returns A map from revision id (lower-case) to its review.
 */
export function indexReviewsByVersion(
  reviews: readonly ReviewStatusRow[]
): ReadonlyMap<string, ReviewStatusRow> {
  const index = new Map<string, ReviewStatusRow>();
  for (const review of reviews) {
    const key = idKey(review.versionId);
    if (!key) continue;
    const seen = index.get(key);
    if (!seen || review.updatedAt > seen.updatedAt) index.set(key, review);
  }
  return index;
}

/** A project's open reviews, collapsed into the one pill a card has room for. */
export interface ProjectReviewSummary {
  /** The project. */
  projectId: string;
  /** The review the pill speaks for — the most urgent, then the most recently updated. */
  review: ReviewStatusRow;
  /** How many open reviews the project has in total. */
  total: number;
  /** How many of them the pill does *not* name — `total - 1`. */
  moreCount: number;
}

/**
 * Rank two reviews for the single pill.
 *
 * @param a - One review.
 * @param b - The other.
 * @returns A negative number when `a` should speak for the project.
 */
function byUrgency(a: ReviewStatusRow, b: ReviewStatusRow): number {
  const urgency = REVIEW_STATE_URGENCY[b.state] - REVIEW_STATE_URGENCY[a.state];
  if (urgency !== 0) return urgency;
  if (a.updatedAt !== b.updatedAt) return a.updatedAt > b.updatedAt ? -1 : 1;
  // Ids break the remaining ties so two renders of the same data never disagree.
  return a.reviewId.localeCompare(b.reviewId);
}

/**
 * Collapse open reviews into one summary per project.
 *
 * @param reviews - Open reviews of any number of projects, in any order.
 * @returns A map from project id (lower-case) to its summary. Projects with no open review are
 *   absent rather than present with a zero, so a card draws no pill at all.
 */
export function summarizeProjectReviews(
  reviews: readonly ReviewStatusRow[]
): ReadonlyMap<string, ProjectReviewSummary> {
  const grouped = new Map<string, ReviewStatusRow[]>();
  for (const review of reviews) {
    const key = idKey(review.projectId);
    if (!key) continue;
    const bucket = grouped.get(key);
    if (bucket) bucket.push(review);
    else grouped.set(key, [review]);
  }

  const summaries = new Map<string, ProjectReviewSummary>();
  for (const [key, bucket] of grouped) {
    const [review] = [...bucket].sort(byUrgency);
    summaries.set(key, {
      projectId: review.projectId,
      review,
      total: bucket.length,
      moreCount: bucket.length - 1,
    });
  }
  return summaries;
}

/**
 * Look a row up in one of the maps above.
 *
 * Both maps are keyed by a lower-case id, and callers hold ids in whatever case their API
 * returned them; this is the one place that difference is handled.
 *
 * @param index - A map from {@link indexReviewsByVersion} or {@link summarizeProjectReviews}.
 * @param id - The revision or project id.
 * @returns The entry, or null.
 */
export function lookupReview<T>(
  index: ReadonlyMap<string, T> | null | undefined,
  id: string | null | undefined
): T | null {
  const key = idKey(id);
  if (!index || !key) return null;
  return index.get(key) ?? null;
}

/* -------------------------------------------------------------------------- */
/* Parsing                                                                    */
/* -------------------------------------------------------------------------- */

/** The states a review row may be in — the guard's allow-list. */
const REVIEW_STATES: readonly ReviewState[] = ['in_review', 'approved', 'changes_requested'];

/**
 * Read a number off an untrusted row.
 *
 * @param value - The field.
 * @returns A finite, non-negative integer; `0` for anything else.
 */
function asCount(value: unknown): number {
  const parsed = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? Math.floor(parsed) : 0;
}

/**
 * Coerce one row of `GET /api/reviews/status` into a {@link ReviewStatusRow}.
 *
 * The screens render this straight into links and accessible names, so a row missing an id or
 * carrying a state this build does not know is dropped rather than drawn: a pill reading
 * `undefined` that links to `/ade/reviews/undefined` is worse than no pill.
 *
 * @param value - One row of the reply.
 * @returns The row, or null when it is not usable.
 */
export function parseReviewStatusRow(value: unknown): ReviewStatusRow | null {
  if (!value || typeof value !== 'object') return null;
  const row = value as Record<string, unknown>;
  const reviewId = typeof row.reviewId === 'string' ? row.reviewId.trim() : '';
  const projectId = typeof row.projectId === 'string' ? row.projectId.trim() : '';
  const versionId = typeof row.versionId === 'string' ? row.versionId.trim() : '';
  const state = row.state as ReviewState;
  if (!reviewId || !projectId || !versionId || !REVIEW_STATES.includes(state)) return null;
  return {
    reviewId,
    projectId,
    versionId,
    versionLabel: typeof row.versionLabel === 'string' && row.versionLabel.trim() ? row.versionLabel : null,
    state,
    round: Math.max(1, asCount(row.round)),
    reviewerCount: asCount(row.reviewerCount),
    approvedCount: asCount(row.approvedCount),
    changesRequestedCount: asCount(row.changesRequestedCount),
    pendingCount: asCount(row.pendingCount),
    updatedAt: typeof row.updatedAt === 'string' ? row.updatedAt : '',
  };
}

/**
 * Coerce a whole `GET /api/reviews/status` reply.
 *
 * @param value - The parsed JSON body.
 * @returns Every usable row; an empty list for a failed or unexpected reply.
 */
export function parseReviewStatusPayload(value: unknown): ReviewStatusRow[] {
  const rows = (value as { reviews?: unknown } | null)?.reviews;
  if (!Array.isArray(rows)) return [];
  return rows.flatMap((row) => {
    const parsed = parseReviewStatusRow(row);
    return parsed ? [parsed] : [];
  });
}
