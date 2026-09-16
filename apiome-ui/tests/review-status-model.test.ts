/**
 * The rules behind the review status pill (COL-2.4, #4520).
 *
 * `lib/review-status.ts` is what stops the four surfaces — version rows, project cards, the
 * projects table and the publish dialog — from each deciding what "in review" looks like. This
 * suite pins the decisions that would otherwise drift:
 *
 *   1. **One vocabulary.** Every state has a label, and the label is also the `Badge` status
 *      string, so the tone comes from `statusVocabulary.ts`.
 *   2. **One link.** `/ade/reviews/{id}`, encoded, on every surface.
 *   3. **One review speaks for a project.** A card has room for one pill, so the most urgent of a
 *      project's open reviews is chosen — deterministically, because the list is capped elsewhere
 *      and an unstable choice would change which pill is drawn between two renders.
 *   4. **Colour is never the only signal.** The pill's accessible name names the revision and what
 *      clicking does.
 *   5. **An unusable row is dropped, not drawn.** A pill reading `undefined` that links to
 *      `/ade/reviews/undefined` is worse than no pill.
 */

import { statusTone } from '@/app/components/ui/statusVocabulary';
import {
  REVIEW_STATE_LABEL,
  REVIEW_STATE_URGENCY,
  indexReviewsByVersion,
  lookupReview,
  parseReviewStatusPayload,
  parseReviewStatusRow,
  reviewPageHref,
  reviewPillTitle,
  reviewTallyText,
  reviewVersionLabel,
  summarizeProjectReviews,
  type ReviewState,
  type ReviewStatusRow,
} from '@lib/review-status';

/** A review row with sane defaults; `over` names only what the case is about. */
function review(over: Partial<ReviewStatusRow> = {}): ReviewStatusRow {
  return {
    reviewId: 'rev-1',
    projectId: 'proj-1',
    versionId: 'ver-1',
    versionLabel: '1.2.0',
    state: 'in_review',
    round: 1,
    reviewerCount: 2,
    approvedCount: 1,
    changesRequestedCount: 0,
    pendingCount: 1,
    updatedAt: '2026-09-01T10:00:00.000Z',
    ...over,
  };
}

describe('the pill vocabulary', () => {
  it('labels all three stored states', () => {
    expect(REVIEW_STATE_LABEL).toEqual({
      in_review: 'In review',
      approved: 'Approved',
      changes_requested: 'Changes requested',
    });
  });

  it('resolves every state through the shared status vocabulary', () => {
    // The pill hands the raw state to `Badge status=`, so a state the vocabulary has not been
    // told about would silently fall back to neutral grey on every surface at once.
    expect(statusTone('in_review')).toBe('warn');
    expect(statusTone('approved')).toBe('ok');
    expect(statusTone('changes_requested')).toBe('danger');
  });

  it('agrees with the `review` lifecycle word the version row already draws', () => {
    expect(statusTone('in_review')).toBe(statusTone('review'));
  });

  it('ranks changes requested above in review above approved', () => {
    expect(REVIEW_STATE_URGENCY.changes_requested).toBeGreaterThan(REVIEW_STATE_URGENCY.in_review);
    expect(REVIEW_STATE_URGENCY.in_review).toBeGreaterThan(REVIEW_STATE_URGENCY.approved);
  });
});

describe('reviewPageHref', () => {
  it('points at the COL-2.2 review page', () => {
    expect(reviewPageHref('abc')).toBe('/ade/reviews/abc');
  });

  it('encodes the id, so nothing in it can escape the segment', () => {
    expect(reviewPageHref('a/b?c')).toBe('/ade/reviews/a%2Fb%3Fc');
  });
});

describe('naming the revision', () => {
  it('prefixes the label with v', () => {
    expect(reviewVersionLabel(review({ versionLabel: '2.0.0' }))).toBe('v2.0.0');
  });

  it('falls back to the short revision id when there is no label', () => {
    expect(reviewVersionLabel(review({ versionLabel: null, versionId: 'abcdef0123456789' }))).toBe(
      'abcdef01'
    );
  });

  it('treats a blank label as no label', () => {
    expect(reviewVersionLabel(review({ versionLabel: '   ', versionId: 'abcdef0123456789' }))).toBe(
      'abcdef01'
    );
  });
});

describe('reviewTallyText', () => {
  it('reads the current round in words', () => {
    expect(reviewTallyText(review())).toBe('1 of 2 approved · 1 pending');
  });

  it('mentions requested changes when there are any', () => {
    expect(
      reviewTallyText(
        review({ reviewerCount: 3, approvedCount: 1, changesRequestedCount: 1, pendingCount: 1 })
      )
    ).toBe('1 of 3 approved · 1 requested changes · 1 pending');
  });
});

describe('reviewPillTitle', () => {
  it('names the revision, the state and what clicking does', () => {
    expect(reviewPillTitle(review())).toBe('v1.2.0 — in review · open the review');
  });

  it('contains the visible label, so the accessible name does not contradict it', () => {
    for (const state of Object.keys(REVIEW_STATE_LABEL) as ReviewState[]) {
      const title = reviewPillTitle(review({ state }));
      expect(title.toLowerCase()).toContain(REVIEW_STATE_LABEL[state].toLowerCase());
    }
  });

  it('says how many more reviews the pill stands for', () => {
    expect(reviewPillTitle(review(), 1)).toContain('1 more open review in this project');
    expect(reviewPillTitle(review(), 3)).toContain('3 more open reviews in this project');
  });
});

describe('indexReviewsByVersion', () => {
  it('keys rows by revision, case-insensitively', () => {
    const index = indexReviewsByVersion([review({ versionId: 'VER-1' })]);
    expect(lookupReview(index, 'ver-1')?.reviewId).toBe('rev-1');
    expect(lookupReview(index, ' VER-1 ')?.reviewId).toBe('rev-1');
  });

  it('keeps the most recently updated when a revision somehow has two', () => {
    // COL-2.1's partial unique index makes this impossible in the database; if it happens the
    // rows disagree, and the one a reader acted on last is the honest answer.
    const index = indexReviewsByVersion([
      review({ reviewId: 'old', updatedAt: '2026-09-01T00:00:00.000Z' }),
      review({ reviewId: 'new', updatedAt: '2026-09-02T00:00:00.000Z' }),
    ]);
    expect(lookupReview(index, 'ver-1')?.reviewId).toBe('new');
  });

  it('drops a row with no revision id', () => {
    expect(indexReviewsByVersion([review({ versionId: '  ' })]).size).toBe(0);
  });
});

describe('summarizeProjectReviews', () => {
  it('leaves a project with no open review out entirely', () => {
    expect(summarizeProjectReviews([]).size).toBe(0);
    expect(lookupReview(summarizeProjectReviews([]), 'proj-1')).toBeNull();
  });

  it('lets the most urgent state speak for the project', () => {
    const summary = lookupReview(
      summarizeProjectReviews([
        review({ reviewId: 'a', versionId: 'v-a', state: 'approved' }),
        review({ reviewId: 'b', versionId: 'v-b', state: 'in_review' }),
        review({ reviewId: 'c', versionId: 'v-c', state: 'changes_requested' }),
      ]),
      'proj-1'
    );
    expect(summary?.review.reviewId).toBe('c');
    expect(summary?.total).toBe(3);
    expect(summary?.moreCount).toBe(2);
  });

  it('breaks a tie on the same state by the most recent activity', () => {
    const summary = lookupReview(
      summarizeProjectReviews([
        review({ reviewId: 'older', versionId: 'v-a', updatedAt: '2026-09-01T00:00:00.000Z' }),
        review({ reviewId: 'newer', versionId: 'v-b', updatedAt: '2026-09-05T00:00:00.000Z' }),
      ]),
      'proj-1'
    );
    expect(summary?.review.reviewId).toBe('newer');
  });

  it('is deterministic when state and instant are identical', () => {
    const rows = [
      review({ reviewId: 'b-id', versionId: 'v-b' }),
      review({ reviewId: 'a-id', versionId: 'v-a' }),
    ];
    const first = lookupReview(summarizeProjectReviews(rows), 'proj-1')?.review.reviewId;
    const second = lookupReview(summarizeProjectReviews([...rows].reverse()), 'proj-1')?.review
      .reviewId;
    expect(first).toBe('a-id');
    expect(second).toBe('a-id');
  });

  it('never mutates the rows it was handed', () => {
    const rows = [
      review({ reviewId: 'a', versionId: 'v-a', state: 'approved' }),
      review({ reviewId: 'b', versionId: 'v-b', state: 'changes_requested' }),
    ];
    summarizeProjectReviews(rows);
    expect(rows.map((row) => row.reviewId)).toEqual(['a', 'b']);
  });

  it('keeps projects apart', () => {
    const summaries = summarizeProjectReviews([
      review({ reviewId: 'a', projectId: 'p1', versionId: 'v-a' }),
      review({ reviewId: 'b', projectId: 'p2', versionId: 'v-b' }),
    ]);
    expect(lookupReview(summaries, 'p1')?.review.reviewId).toBe('a');
    expect(lookupReview(summaries, 'p2')?.review.reviewId).toBe('b');
    expect(lookupReview(summaries, 'p1')?.moreCount).toBe(0);
  });
});

describe('lookupReview', () => {
  it('answers null for a missing map or a blank id', () => {
    expect(lookupReview(null, 'x')).toBeNull();
    expect(lookupReview(new Map(), '')).toBeNull();
    expect(lookupReview(new Map(), undefined)).toBeNull();
  });
});

describe('parsing the reply', () => {
  const wire = {
    reviewId: 'r1',
    projectId: 'p1',
    versionId: 'v1',
    versionLabel: '3.1.0',
    state: 'approved',
    round: 2,
    reviewerCount: 2,
    approvedCount: 2,
    changesRequestedCount: 0,
    pendingCount: 0,
    updatedAt: '2026-09-09T00:00:00.000Z',
  };

  it('reads a well-formed row', () => {
    expect(parseReviewStatusRow(wire)).toEqual(wire);
  });

  it('drops a row missing an id or carrying an unknown state', () => {
    expect(parseReviewStatusRow({ ...wire, reviewId: '' })).toBeNull();
    expect(parseReviewStatusRow({ ...wire, projectId: '   ' })).toBeNull();
    expect(parseReviewStatusRow({ ...wire, versionId: undefined })).toBeNull();
    expect(parseReviewStatusRow({ ...wire, state: 'withdrawn' })).toBeNull();
    expect(parseReviewStatusRow(null)).toBeNull();
    expect(parseReviewStatusRow('in_review')).toBeNull();
  });

  it('coerces counts to non-negative integers and the round to at least one', () => {
    const row = parseReviewStatusRow({
      ...wire,
      round: 0,
      reviewerCount: '3',
      approvedCount: -2,
      pendingCount: 1.9,
      changesRequestedCount: null,
    });
    expect(row).toMatchObject({
      round: 1,
      reviewerCount: 3,
      approvedCount: 0,
      pendingCount: 1,
      changesRequestedCount: 0,
    });
  });

  it('reads a blank label as no label', () => {
    expect(parseReviewStatusRow({ ...wire, versionLabel: '  ' })?.versionLabel).toBeNull();
  });

  it('keeps the usable rows of a mixed payload and ignores anything else', () => {
    expect(parseReviewStatusPayload({ reviews: [wire, { ...wire, state: 'nope' }] })).toHaveLength(1);
    expect(parseReviewStatusPayload({ success: false })).toEqual([]);
    expect(parseReviewStatusPayload(null)).toEqual([]);
    expect(parseReviewStatusPayload({ reviews: 'nope' })).toEqual([]);
  });
});
