/**
 * The review page's rules — COL-2.2 (#4518).
 *
 * `/ade/reviews/{id}` is where a reviewer decides whether a draft version is ready: a header with
 * the version, the requester and the review's state; **Changes** (the classified diff against the
 * project's newest published version), **Spec** (the version's OpenAPI document, read-only) and
 * **Discussion** (the version's open comment threads) tabs; and a sticky decision bar.
 *
 * Everything here is framework-free so the BFF routes, the components and the tests share one set
 * of rules:
 *
 * - the wire types of apiome-rest's review API (COL-2.1, `apiome-rest/docs/reviews.md`);
 * - the tab vocabulary and `?tab=` parsing;
 * - the header's badge, progress and title text;
 * - {@link decisionBarModel}, which decides what the decision bar offers the viewer, and
 *   {@link validateDecisionNote}, which makes a note required for **Request changes**;
 * - human messages for apiome-rest's stable `review-*` refusal codes;
 * - the Changes tab's shaping of `POST /v1/diff/{tenant}/classified` rows into the grouped
 *   changelog view `lib/version-changelog.ts` already renders for stored changelogs;
 * - {@link newestPublishedRevision}, the baseline rule.
 */

import {
  SEVERITY_ORDER,
  decodeJsonPointer,
  groupChangelogEntries,
  type ChangelogEntry,
  type ChangelogSeverity,
  type ChangelogSeveritySection,
} from './version-changelog';

/* -------------------------------------------------------------------------- */
/* Wire types (apiome-rest COL-2.1)                                            */
/* -------------------------------------------------------------------------- */

/** A stored review's state. A version with no open review is a draft and has no review row. */
export type ReviewState = 'in_review' | 'approved' | 'changes_requested';

/** A reviewer row's decision; `pending` until the reviewer decides. */
export type ReviewDecision = 'approve' | 'request_changes' | 'pending';

/** The decisions a reviewer can record. */
export type RecordableDecision = Exclude<ReviewDecision, 'pending'>;

/** Every decision a reviewer can record, in the order the bar shows them. */
export const RECORDABLE_DECISIONS: readonly RecordableDecision[] = ['request_changes', 'approve'];

/** The longest note apiome-rest stores with a decision, in characters. */
export const REVIEW_NOTE_MAX_LENGTH = 5000;

/** One reviewer's row in one round of a review. */
export interface ReviewerDecisionRow {
  /** The row id. */
  id: string;
  /** The review it belongs to. */
  review_id: string;
  /** The round it was created for. */
  round: number;
  /** The reviewer; null once that user was deleted. */
  user_id: string | null;
  /** The reviewer's display name. */
  user_name: string | null;
  /** What they decided. */
  decision: ReviewDecision;
  /** The note recorded with the decision. */
  note: string | null;
  /** When they decided; null while pending. */
  decided_at: string | null;
  /** When they were asked. */
  created_at: string;
}

/** A review, with the tally of its current round. */
export interface ReviewRecord {
  id: string;
  tenant_id: string;
  project_id: string;
  /** The revision under review. */
  version_id: string;
  /** Its label, e.g. `1.2.0`. */
  version_label: string | null;
  requested_by: string | null;
  requested_by_name: string | null;
  state: ReviewState;
  /** The current round; each re-request starts the next. */
  round: number;
  spec_fingerprint: string;
  reviewer_count: number;
  approved_count: number;
  changes_requested_count: number;
  pending_count: number;
  /** When it was withdrawn; null while open. */
  closed_at: string | null;
  closed_by: string | null;
  created_at: string;
  updated_at: string;
}

/** A review with its reviewers and history, as `GET …/reviews/{id}` returns it. */
export interface ReviewDetail {
  review: ReviewRecord;
  /** The current round's reviewers. */
  reviewers: ReviewerDecisionRow[];
  /** Every earlier round's rows, oldest round first. */
  history: ReviewerDecisionRow[];
  /** True when the version's content no longer matches the current round; null when withdrawn. */
  spec_changed: boolean | null;
}

/** The project a review belongs to, as the page names and links it. */
export interface ReviewProjectRef {
  id: string;
  name: string;
  slug: string;
}

/** What `GET /api/reviews/{id}` answers with, beside `success`. */
export interface ReviewPagePayload {
  review: ReviewDetail;
  project: ReviewProjectRef;
  /** The signed-in user, so the page can tell whether they are a reviewer. */
  viewerId: string | null;
}

/* -------------------------------------------------------------------------- */
/* Tabs                                                                       */
/* -------------------------------------------------------------------------- */

/** The page's tabs, in order. */
export const REVIEW_TABS = ['changes', 'spec', 'discussion'] as const;

/** One tab. */
export type ReviewTabId = (typeof REVIEW_TABS)[number];

/** Each tab's label. */
export const REVIEW_TAB_LABELS: Readonly<Record<ReviewTabId, string>> = {
  changes: 'Changes',
  spec: 'Spec',
  discussion: 'Discussion',
};

/**
 * The tab a `?tab=` value opens.
 *
 * @param value - The query value (Next.js may hand over an array for a repeated key).
 * @returns That tab, or `changes` for anything else.
 */
export function reviewTabFromQuery(value: string | readonly string[] | null | undefined): ReviewTabId {
  const raw = Array.isArray(value) ? value[0] : value;
  return (REVIEW_TABS as readonly string[]).includes(raw as string) ? (raw as ReviewTabId) : 'changes';
}

/* -------------------------------------------------------------------------- */
/* Header                                                                     */
/* -------------------------------------------------------------------------- */

/** The `Badge` variants the page uses. */
export type ReviewBadgeVariant = 'warning' | 'success' | 'error' | 'secondary';

/** A badge: its text and tone. */
export interface ReviewBadge {
  label: string;
  variant: ReviewBadgeVariant;
}

/**
 * The header's status badge.
 *
 * `in_review` takes DESIGN.md's `review` tone (warn); a withdrawn review is neutral whatever state
 * it was left in, because nothing more will happen to it.
 *
 * @param review - The review's state and closure.
 * @returns The badge.
 */
export function reviewStatusBadge(review: Pick<ReviewRecord, 'state' | 'closed_at'>): ReviewBadge {
  if (review.closed_at) return { label: 'Withdrawn', variant: 'secondary' };
  switch (review.state) {
    case 'approved':
      return { label: 'Approved', variant: 'success' };
    case 'changes_requested':
      return { label: 'Changes requested', variant: 'error' };
    default:
      return { label: 'In review', variant: 'warning' };
  }
}

/** Each decision, as a reviewer row's badge says it. */
export const DECISION_LABELS: Readonly<Record<ReviewDecision, string>> = {
  approve: 'Approved',
  request_changes: 'Requested changes',
  pending: 'Pending',
};

/**
 * A decision's badge tone.
 *
 * @param decision - The decision.
 * @returns The variant.
 */
export function decisionBadgeVariant(decision: ReviewDecision): ReviewBadgeVariant {
  if (decision === 'approve') return 'success';
  if (decision === 'request_changes') return 'error';
  return 'secondary';
}

/**
 * The current round's tally, in words: `1 of 2 approved · 1 pending`.
 *
 * @param review - The review.
 * @returns The sentence.
 */
export function reviewProgressText(
  review: Pick<ReviewRecord, 'reviewer_count' | 'approved_count' | 'changes_requested_count' | 'pending_count'>
): string {
  const parts = [`${review.approved_count} of ${review.reviewer_count} approved`];
  if (review.changes_requested_count > 0) parts.push(`${review.changes_requested_count} requested changes`);
  if (review.pending_count > 0) parts.push(`${review.pending_count} pending`);
  return parts.join(' · ');
}

/* -------------------------------------------------------------------------- */
/* Decision bar                                                               */
/* -------------------------------------------------------------------------- */

/** What the decision bar offers. */
export type DecisionBarMode =
  /** The viewer is a pending reviewer of a round that can take decisions: show the form. */
  | 'decide'
  /** The viewer already decided in this round. */
  | 'decided'
  /** The viewer is pending, but someone requested changes, so the round is decided. */
  | 'round-decided'
  /** The spec changed after the round was requested; nobody can decide until a re-request. */
  | 'stale'
  /** The viewer is not a reviewer in this round. */
  | 'not-reviewer'
  /** The review was withdrawn. */
  | 'withdrawn';

/** The decision bar's state for one viewer. */
export interface DecisionBarModel {
  mode: DecisionBarMode;
  /** The sentence the bar shows. */
  message: string;
  /** The viewer's own row in the current round, when they have one. */
  mine: ReviewerDecisionRow | null;
}

/**
 * Compare two ids the way apiome-rest does: canonical UUIDs, case-insensitively.
 *
 * @param a - One id.
 * @param b - The other.
 * @returns True when both are present and equal.
 */
export function sameId(a: string | null | undefined, b: string | null | undefined): boolean {
  return Boolean(a && b && a.trim().toLowerCase() === b.trim().toLowerCase());
}

/**
 * Decide what the decision bar offers the viewer.
 *
 * The order mirrors apiome-rest's refusals, so the bar never offers a button the API would refuse:
 * a withdrawn review first, then whether the viewer is a reviewer of the current round, whether
 * they already decided, whether the round is still open, and whether the spec still matches it.
 *
 * @param detail - The review.
 * @param viewerId - The signed-in user.
 * @returns The bar's mode, sentence and the viewer's row.
 */
export function decisionBarModel(detail: ReviewDetail, viewerId: string | null): DecisionBarModel {
  const mine = detail.reviewers.find((row) => sameId(row.user_id, viewerId)) ?? null;
  if (detail.review.closed_at) {
    return { mode: 'withdrawn', message: 'This review was withdrawn. Its decisions stay on record.', mine };
  }
  if (!mine) {
    return {
      mode: 'not-reviewer',
      message: 'You are not a reviewer in this round, so there is nothing for you to decide.',
      mine,
    };
  }
  if (mine.decision !== 'pending') {
    return {
      mode: 'decided',
      message:
        mine.decision === 'approve' ? 'You approved this round.' : 'You requested changes in this round.',
      mine,
    };
  }
  if (detail.review.state !== 'in_review') {
    return {
      mode: 'round-decided',
      message:
        'Another reviewer requested changes, so this round is decided. It reopens when the review is re-requested.',
      mine,
    };
  }
  if (detail.spec_changed === true) {
    return {
      mode: 'stale',
      message:
        'The spec changed after this round was requested. The review has to be re-requested before anyone can decide.',
      mine,
    };
  }
  return {
    mode: 'decide',
    message: 'Approve this version, or request changes and say what needs to change.',
    mine,
  };
}

/**
 * Whether a value is a decision a reviewer can record.
 *
 * @param value - The candidate.
 * @returns True for `approve` and `request_changes`.
 */
export function isRecordableDecision(value: unknown): value is RecordableDecision {
  return value === 'approve' || value === 'request_changes';
}

/**
 * Check a decision's note.
 *
 * A note is optional with **Approve** and required with **Request changes** — the reviewer has to
 * say what needs to change.
 *
 * @param decision - The decision.
 * @param note - The note as typed.
 * @returns What is wrong with the note, or null when it is fine.
 */
export function validateDecisionNote(decision: RecordableDecision, note: string | null | undefined): string | null {
  const text = note ?? '';
  if (decision === 'request_changes' && !text.trim()) {
    return 'Say what needs to change before requesting changes.';
  }
  if (text.length > REVIEW_NOTE_MAX_LENGTH) {
    return `Keep the note to ${REVIEW_NOTE_MAX_LENGTH.toLocaleString('en-US')} characters.`;
  }
  return null;
}

/**
 * The body apiome-rest's decision endpoint takes.
 *
 * @param decision - The decision.
 * @param note - The note as typed; a blank note is left out.
 * @returns `{decision}` or `{decision, note}`.
 */
export function decisionPayload(
  decision: RecordableDecision,
  note: string | null | undefined
): { decision: RecordableDecision; note?: string } {
  return note && note.trim() ? { decision, note } : { decision };
}

/* -------------------------------------------------------------------------- */
/* Refusals                                                                   */
/* -------------------------------------------------------------------------- */

/** What to tell a reviewer for each of apiome-rest's review refusal codes. */
export const REVIEW_ERROR_MESSAGES: Readonly<Record<string, string>> = {
  'review-not-found': 'This review does not exist, or it belongs to another workspace.',
  'review-project-not-found': 'This review does not exist, or it belongs to another workspace.',
  'review-version-not-found': 'The version under review no longer exists.',
  'review-not-reviewer': 'Only a reviewer of the current round can decide.',
  'review-already-decided': 'You already decided in this round. Decisions cannot be changed.',
  'review-not-in-review': 'This round is already decided. The review has to be re-requested first.',
  'review-closed': 'This review was withdrawn.',
  'review-spec-changed':
    'The spec changed after this round was requested. The review has to be re-requested before anyone can decide.',
  'review-version-published': 'This version has been published, so it can no longer be reviewed.',
  'review-conflict': 'The review changed while you were deciding. Reload it and try again.',
};

/**
 * The message for a refusal.
 *
 * @param code - apiome-rest's `detail.code`, when there was one.
 * @param fallback - What to say for an unknown or missing code.
 * @returns The message.
 */
export function reviewErrorMessage(code: string | null | undefined, fallback: string): string {
  return (code && REVIEW_ERROR_MESSAGES[code]) || fallback;
}

/* -------------------------------------------------------------------------- */
/* Changes                                                                    */
/* -------------------------------------------------------------------------- */

/** One row of `POST /v1/diff/{tenant}/classified` (camelCase). */
export interface ClassifiedChange {
  ruleId: string;
  severity: string;
  pointer: string;
  before?: unknown;
  after?: unknown;
  unclassified?: boolean;
  changeKind?: string | null;
  consumers?: string[] | null;
}

/** A revision the Changes tab names. */
export interface ReviewRevisionRef {
  id: string;
  label: string | null;
}

/** What `GET /api/reviews/{id}/changes` answers with, beside `success`. */
export interface ReviewChangesPayload {
  /** The version under review. */
  head: ReviewRevisionRef;
  /** The newest published version it is compared with; null when nothing is published. */
  baseline: ReviewRevisionRef | null;
  /** True when there is no published version, so this would be the first publication. */
  initialPublication: boolean;
  /** The classified changes; empty when there is no baseline or classification failed. */
  changes: ClassifiedChange[];
  /** Counts per severity, plus `total`. */
  counts: Record<string, number>;
  maxSeverity: ChangelogSeverity | null;
  /** Why classification failed, when it did; the tab then falls back to the plain diff. */
  classifiedError: string | null;
}

/**
 * The group a change is listed under — apiome-rest's `changelog_generator.path_group_for_pointer`,
 * mirrored so the live diff groups exactly as a stored changelog does.
 *
 * @param pointer - The change's JSON Pointer, e.g. `/paths/~1pets/get/responses/200`.
 * @returns `/paths/~1pets`, `/components/schemas/Pet`, `/servers`, `/info`, and so on.
 */
export function pathGroupForPointer(pointer: string): string {
  if (!pointer || pointer === '/') return '/';
  const raw = pointer.startsWith('/') ? pointer : `/${pointer}`;
  const parts = raw.split('/').filter((part) => part !== '');
  if (parts.length === 0) return '/';
  const [head] = parts;
  if (head === 'paths' && parts.length >= 2) return `/${parts.slice(0, 2).join('/')}`;
  if (head === 'components' && parts.length >= 3) return `/${parts.slice(0, 3).join('/')}`;
  if (head === 'components' && parts.length >= 2) return `/${parts.slice(0, 2).join('/')}`;
  if (['servers', 'tags', 'security', 'webhooks'].includes(head)) return `/${head}`;
  if (head === 'info') return '/info';
  if (parts.length >= 2) return `/${parts.slice(0, 2).join('/')}`;
  return `/${head}`;
}

/**
 * A readable spelling of a JSON Pointer: `/paths/~1pets/get` → `paths › /pets › get`.
 *
 * @param pointer - The pointer.
 * @returns The segments joined with `›`, or `Document` for the root.
 */
export function readablePointer(pointer: string): string {
  const segments = decodeJsonPointer(pointer);
  return segments.length ? segments.join(' › ') : 'Document';
}

/**
 * A rule id as words: `response-property-removed` → `Response property removed`.
 *
 * @param ruleId - The taxonomy rule id.
 * @returns The sentence-case phrase, or an empty string for a blank id.
 */
export function humanizeRuleId(ruleId: string | null | undefined): string {
  const words = (ruleId ?? '')
    .split(/[-_.:/\s]+/)
    .map((word) => word.trim())
    .filter(Boolean)
    .join(' ')
    .toLowerCase();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : '';
}

/**
 * The one-line summary of a live classified change.
 *
 * The live endpoint's JSON carries the rule id but not the taxonomy's summary sentence (only the
 * stored `ctg.changelog.v1` has it), so the summary is the rule id in words — with the generator's
 * own fallbacks for an unclassified change or a change with no rule.
 *
 * @param change - The change.
 * @returns The summary.
 */
export function classifiedChangeSummary(change: Pick<ClassifiedChange, 'ruleId' | 'unclassified' | 'changeKind'>): string {
  if (change.unclassified) return 'Unclassified change (treated as breaking)';
  const rule = humanizeRuleId(change.ruleId);
  if (rule) return rule;
  return change.changeKind ? `Change of kind ${change.changeKind}` : 'Change';
}

/**
 * Shape live classified changes as changelog entries, so they group and render like a stored
 * changelog.
 *
 * @param changes - The endpoint's rows.
 * @param fromVersion - The baseline's label.
 * @param toVersion - The head's label.
 * @returns One entry per change, in the endpoint's order. An unknown severity becomes `breaking`
 *   when the change is unclassified (the endpoint's rule) and `docs-only` otherwise.
 */
export function classifiedChangesToEntries(
  changes: readonly ClassifiedChange[],
  fromVersion: string | null,
  toVersion: string | null
): ChangelogEntry[] {
  return changes.map((change) => {
    const known = SEVERITY_ORDER.includes(change.severity as ChangelogSeverity);
    const severity: ChangelogSeverity = known
      ? (change.severity as ChangelogSeverity)
      : change.unclassified
        ? 'breaking'
        : 'docs-only';
    return {
      severity,
      pathGroup: pathGroupForPointer(change.pointer),
      pointer: change.pointer,
      ruleId: change.ruleId,
      changeKind: change.changeKind ?? '',
      summary: classifiedChangeSummary(change),
      before: change.before,
      after: change.after,
      unclassified: change.unclassified,
      fromVersion,
      toVersion,
    };
  });
}

/**
 * How many changes, in words.
 *
 * @param count - The number of changes.
 * @returns `1 change`, `3 changes`.
 */
export function changeCountText(count: number): string {
  return `${count} ${count === 1 ? 'change' : 'changes'}`;
}

/**
 * The Changes tab's sections: severity (breaking first), then path group.
 *
 * @param payload - The changes route's payload.
 * @returns The sections, empty when there is nothing to show.
 */
export function groupReviewChanges(
  payload: Pick<ReviewChangesPayload, 'changes' | 'baseline' | 'head'>
): ChangelogSeveritySection[] {
  return groupChangelogEntries(
    classifiedChangesToEntries(payload.changes, payload.baseline?.label ?? null, payload.head.label)
  );
}

/* -------------------------------------------------------------------------- */
/* Baseline and spec                                                          */
/* -------------------------------------------------------------------------- */

/** The part of a version row the baseline rule reads. */
export interface RevisionRow {
  id: string;
  version_id: string;
  published?: boolean | null;
  published_at?: string | null;
  created_at?: string | null;
}

/**
 * The newest published revision — the version a review's Changes tab compares against.
 *
 * The same rule as the Versions screen's `lastPublishedVersion`: by `published_at`, falling back to
 * `created_at`. It is restated here because that function is typed to the dashboard's full
 * `Version` row, which the BFF does not have.
 *
 * @param rows - The project's revisions.
 * @param excludeId - A revision never to choose (the one under review).
 * @returns The revision, or null when nothing else is published.
 */
export function newestPublishedRevision<T extends RevisionRow>(
  rows: readonly T[],
  excludeId?: string | null
): T | null {
  let best: T | null = null;
  let bestTime = Number.NEGATIVE_INFINITY;
  for (const row of rows) {
    if (!row.published || (excludeId && sameId(row.id, excludeId))) continue;
    const time = new Date(row.published_at ?? row.created_at ?? '').getTime();
    if (Number.isNaN(time)) continue;
    if (time > bestTime) {
      best = row;
      bestTime = time;
    }
  }
  return best;
}

/** Which document the spec route reads: the version under review, or its baseline. */
export type ReviewSpecSide = 'head' | 'base';

/**
 * The side a `?side=` value names.
 *
 * @param value - The query value.
 * @returns `base` only for exactly `base`; `head` otherwise.
 */
export function reviewSpecSideFromQuery(value: string | null | undefined): ReviewSpecSide {
  return value === 'base' ? 'base' : 'head';
}
