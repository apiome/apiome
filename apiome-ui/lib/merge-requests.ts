/**
 * Draft branches and merge requests — the UI model of COL-4.3 (#4527).
 *
 * The shapes apiome-rest returns from `…/projects/{project}/draft-branches` and
 * `…/projects/{project}/merge-requests`, and the pure helpers the Versions screen's
 * **Merge requests** tab, its two dialogs, the merge request page and their BFF routes share:
 * labels and badge tones, form validation, request payloads, refusal messages, and the page's tabs.
 *
 * A merge request composes pieces that already exist — the review of the branch tip (COL-2.1), the
 * merge session (the only merge path), and the classified diff (CTG-1.x) — so this module carries
 * no rules of its own beyond how to show them.
 */

import type { ReviewDetail } from './review-page';
import { isValidVersionBranchName } from './version-branch-utils';

/* -------------------------------------------------------------------------- */
/* Shapes (apiome-rest, snake_case)                                           */
/* -------------------------------------------------------------------------- */

/** A merge request's lifecycle state. */
export type MergeRequestState = 'open' | 'merged' | 'closed';

/** A draft branch, with the version line it was drafted off. */
export interface DraftBranchRecord {
  id: string;
  project_id: string;
  name: string;
  /** The draft revision edits land on. */
  tip_revision_id: string;
  tip_version_label: string | null;
  base_branch_id: string | null;
  base_branch_name: string | null;
  branched_from_revision_id: string | null;
  created_by: string | null;
  created_at: string | null;
}

/** One stored merge request. */
export interface MergeRequestRecord {
  id: string;
  tenant_id: string;
  project_id: string;
  title: string;
  description: string | null;
  state: MergeRequestState;
  source_branch_id: string | null;
  source_branch_name: string;
  target_branch_id: string | null;
  target_branch_name: string;
  review_id: string | null;
  merge_session_id: string | null;
  merged_version_id: string | null;
  created_by: string | null;
  created_by_name: string | null;
  created_at: string;
  updated_at: string;
  merged_by: string | null;
  merged_at: string | null;
  closed_by: string | null;
  closed_at: string | null;
}

/** One reason a merge request cannot merge yet. */
export interface MergeBlocker {
  code: string;
  message: string;
}

/** One conflicting path of the merge session. */
export interface MergeConflict {
  path: string;
  kinds: string[];
}

/** Whether the merge request can merge now. */
export interface MergeReadiness {
  can_merge: boolean;
  blockers: MergeBlocker[];
  approval: Record<string, unknown> | null;
}

/** The merge session as apiome-rest serializes it (camelCase, as the merge routes do). */
export interface MergeSessionSummary {
  id: string;
  status: 'preview' | 'resolving' | 'applied' | 'aborted';
  sourceBranchName: string;
  targetBranchName: string;
  mergeBaseVersionId: string;
  sourceTipVersionId: string;
  targetTipVersionId: string;
}

/** A merge request with everything the page shows. */
export interface MergeRequestDetail {
  merge_request: MergeRequestRecord;
  source_tip_revision_id: string | null;
  source_tip_version_label: string | null;
  target_tip_revision_id: string | null;
  target_tip_version_label: string | null;
  merge_base_revision_id: string | null;
  merge_base_version_label: string | null;
  review: ReviewDetail | null;
  review_outdated: boolean;
  merge_session: MergeSessionSummary | null;
  conflicts: MergeConflict[];
  readiness: MergeReadiness;
}

/** A tenant member who can be asked to review. */
export interface ReviewerCandidate {
  user_id: string;
  name: string | null;
  email: string | null;
}

/** What the merge request page loads. */
export interface MergeRequestPagePayload {
  mergeRequest: MergeRequestDetail;
  project: { id: string; name: string; slug: string };
  viewerId: string | null;
}

/* -------------------------------------------------------------------------- */
/* Labels                                                                     */
/* -------------------------------------------------------------------------- */

/** A badge's tone, as `ui/Badge` takes it. */
export type MergeRequestBadgeVariant = 'default' | 'success' | 'secondary';

/** Each state's badge. */
export const MERGE_REQUEST_STATE_BADGE: Readonly<
  Record<MergeRequestState, { label: string; variant: MergeRequestBadgeVariant }>
> = {
  open: { label: 'Open', variant: 'default' },
  merged: { label: 'Merged', variant: 'success' },
  closed: { label: 'Closed', variant: 'secondary' },
};

/** The states the list filter offers, in order. */
export const MERGE_REQUEST_FILTERS: ReadonlyArray<MergeRequestState> = ['open', 'merged', 'closed'];

/**
 * The one-line summary of where a merge request stands.
 *
 * @param detail - The merge request.
 * @returns E.g. "Ready to merge", "Merged into main", or the first blocker's message.
 */
export function readinessSummary(detail: Pick<MergeRequestDetail, 'merge_request' | 'readiness'>): string {
  const { merge_request: record, readiness } = detail;
  if (record.state === 'merged') return `Merged into ${record.target_branch_name}.`;
  if (record.state === 'closed') return 'Closed without merging.';
  if (readiness.can_merge) return `Ready to merge into ${record.target_branch_name}.`;
  const count = readiness.blockers.length;
  return count === 1 ? '1 thing to do before this can merge.' : `${count} things to do before this can merge.`;
}

/**
 * The merge request page's address.
 *
 * @param mergeRequestId - The merge request.
 * @returns `/ade/merge-requests/{id}`.
 */
export function mergeRequestHref(mergeRequestId: string): string {
  return `/ade/merge-requests/${encodeURIComponent(mergeRequestId)}`;
}

/* -------------------------------------------------------------------------- */
/* The page's tabs                                                            */
/* -------------------------------------------------------------------------- */

/** The merge request page's tabs, in order. */
export const MERGE_REQUEST_TABS = ['changes', 'conflicts', 'review'] as const;

/** A tab id. */
export type MergeRequestTabId = (typeof MERGE_REQUEST_TABS)[number];

/** Each tab's label. */
export const MERGE_REQUEST_TAB_LABELS: Readonly<Record<MergeRequestTabId, string>> = {
  changes: 'Changes',
  conflicts: 'Conflicts',
  review: 'Review',
};

/**
 * The tab `?tab=` names, or the Changes tab.
 *
 * @param value - The query value.
 * @returns A tab id.
 */
export function mergeRequestTabFromQuery(value: string | string[] | undefined): MergeRequestTabId {
  const raw = Array.isArray(value) ? value[0] : value;
  return (MERGE_REQUEST_TABS as ReadonlyArray<string>).includes(raw ?? '') ? (raw as MergeRequestTabId) : 'changes';
}

/* -------------------------------------------------------------------------- */
/* Forms                                                                      */
/* -------------------------------------------------------------------------- */

/** The New draft branch dialog's fields. */
export interface DraftBranchForm {
  name: string;
  /** The version line (branch name) to draft off. */
  baseBranch: string;
  /** Optional version label for the draft revision; blank takes the next patch version. */
  versionLabel: string;
}

/** A semantic version label, as apiome-rest's `parse_semantic_version` accepts it. */
const SEMVER_RE = /^v?\d+\.\d+\.\d+$/;

/**
 * What is wrong with the New draft branch form, or null when it can be sent.
 *
 * @param form - The fields as typed.
 * @param existingBranchNames - Names already taken in the project.
 * @returns A message fit to show under the form, or null.
 */
export function draftBranchFormError(form: DraftBranchForm, existingBranchNames: ReadonlyArray<string>): string | null {
  const name = form.name.trim();
  if (!name) return 'Name the branch.';
  if (!isValidVersionBranchName(name)) {
    return 'Branch names start with a letter and use only letters, digits, . _ - / (max 255 characters).';
  }
  if (existingBranchNames.includes(name)) return `A branch named ${name} already exists.`;
  if (!form.baseBranch.trim()) return 'Choose the version line to draft off.';
  const label = form.versionLabel.trim();
  if (label && !SEMVER_RE.test(label)) return 'The version label must look like 1.4.1.';
  return null;
}

/**
 * The body of `POST …/draft-branches`.
 *
 * @param form - The fields as typed.
 * @returns `{name, base_branch, version_label?}`.
 */
export function draftBranchPayload(form: DraftBranchForm): {
  name: string;
  base_branch: string;
  version_label?: string;
} {
  const label = form.versionLabel.trim();
  return { name: form.name.trim(), base_branch: form.baseBranch.trim(), ...(label ? { version_label: label } : {}) };
}

/** The Open merge request dialog's fields. */
export interface OpenMergeRequestForm {
  sourceBranch: string;
  targetBranch: string;
  title: string;
  description: string;
  reviewers: string[];
}

/** The longest title apiome-rest stores. */
export const MERGE_REQUEST_TITLE_MAX = 200;

/** The longest description apiome-rest stores. */
export const MERGE_REQUEST_DESCRIPTION_MAX = 5000;

/**
 * What is wrong with the Open merge request form, or null when it can be sent.
 *
 * @param form - The fields as typed.
 * @returns A message fit to show under the form, or null.
 */
export function openMergeRequestFormError(form: OpenMergeRequestForm): string | null {
  if (!form.sourceBranch.trim()) return 'Choose the draft branch to merge.';
  if (!form.targetBranch.trim()) return 'Choose the version line to merge into.';
  if (form.sourceBranch.trim() === form.targetBranch.trim()) return 'A branch cannot be merged into itself.';
  if (!form.title.trim()) return 'Give the merge request a title.';
  if (form.title.trim().length > MERGE_REQUEST_TITLE_MAX) return `Keep the title under ${MERGE_REQUEST_TITLE_MAX} characters.`;
  if (form.description.length > MERGE_REQUEST_DESCRIPTION_MAX) {
    return `Keep the description under ${MERGE_REQUEST_DESCRIPTION_MAX} characters.`;
  }
  if (form.reviewers.length === 0) return 'Ask at least one reviewer.';
  return null;
}

/**
 * The body of `POST …/merge-requests`.
 *
 * @param form - The fields as typed.
 * @returns `{source_branch, target_branch, title, description?, reviewers}`.
 */
export function openMergeRequestPayload(form: OpenMergeRequestForm): {
  source_branch: string;
  target_branch: string;
  title: string;
  description?: string;
  reviewers: string[];
} {
  const description = form.description.trim();
  return {
    source_branch: form.sourceBranch.trim(),
    target_branch: form.targetBranch.trim(),
    title: form.title.trim(),
    ...(description ? { description } : {}),
    reviewers: Array.from(new Set(form.reviewers)),
  };
}

/**
 * The line a draft branch defaults to merging into.
 *
 * @param drafts - The project's draft branches.
 * @param sourceBranch - The chosen draft branch's name.
 * @returns The line it was drafted off, or an empty string.
 */
export function defaultTargetBranch(drafts: ReadonlyArray<DraftBranchRecord>, sourceBranch: string): string {
  return drafts.find((draft) => draft.name === sourceBranch)?.base_branch_name ?? '';
}

/* -------------------------------------------------------------------------- */
/* Refusals                                                                   */
/* -------------------------------------------------------------------------- */

/** What each refusal code means to the person who pressed the button. */
const ERROR_MESSAGES: Readonly<Record<string, string>> = {
  'mr-project-not-found': 'This project no longer exists.',
  'mr-not-found': 'This merge request no longer exists.',
  'mr-branch-not-found': 'That branch no longer exists. Refresh and try again.',
  'mr-branch-exists': 'A branch with that name already exists.',
  'mr-invalid-branch-name': 'Branch names start with a letter and use only letters, digits, . _ - /.',
  'mr-invalid-label': 'The version label must look like 1.4.1.',
  'mr-label-taken': 'That version label is already used in this project.',
  'mr-not-draft-branch': 'Only a draft branch can be merged through a merge request.',
  'mr-same-branch': 'A branch cannot be merged into itself.',
  'mr-already-open': 'This branch already has an open merge request.',
  'mr-not-open': 'This merge request is already merged or closed.',
  'mr-not-ready': 'This merge request is not ready to merge yet.',
  'mr-conflicts': 'The branch conflicts with the line. Update the branch, then check again.',
  'mr-forbidden': 'This action needs a signed-in user.',
  'review-invalid-reviewers': 'Choose reviewers who are members of this workspace.',
  'review-self-review': 'You cannot review your own merge request.',
  'review-forbidden': 'Only the person who requested the review, or an administrator, can withdraw it.',
  STALE_HEAD: 'The version line moved while merging. Check again, then merge.',
  PUBLISHED_IMMUTABLE:
    'The tip of the version line is published and immutable. A tenant administrator can merge with a reason.',
  MERGE_BLOCKED_BY_COMPAT_GATE: 'The project compatibility gate blocked this merge.',
};

/**
 * A refusal, said plainly.
 *
 * @param code - The refusal code apiome-rest sent, if any.
 * @param fallback - apiome-rest's own message, shown for an unknown code.
 * @returns The message.
 */
export function mergeRequestErrorMessage(code: string | null | undefined, fallback: string): string {
  return (code && ERROR_MESSAGES[code]) || fallback;
}
