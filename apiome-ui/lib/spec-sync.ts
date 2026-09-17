/**
 * Three-way spec synchronization rules, framework-free — GNC-2.3 (#4739).
 *
 * The Synchronization section of the Versions screen's Repository tab and its BFF routes share this
 * file: the wire shapes apiome-rest answers with, the whitelist of what a browser may ask for, and
 * the sentences, tones and value renderings a merge result is drawn with.
 *
 * The one thing worth restating here, because it decides every sentence below: **a merge result is
 * a reading, never a write.** Computing one reads three documents and records a row; settling a
 * conflict records which side a person chose. Neither changes the draft. So the panel says "would
 * apply", not "applied to your draft", and "keep" rather than "revert" — because nothing has
 * happened to the version and nothing is about to.
 *
 * Nothing here touches React, `fetch`, or the DOM, so every rule below is asserted directly.
 */

/** Where a merge result stands. Mirrors apiome-rest's `app.spec_sync`. */
export type SyncPlanStatus = 'clean' | 'mergeable' | 'conflicted' | 'resolved';

/** Why a merge result may not be turned into an edit of the draft. */
export type SyncGuard = 'none' | 'review_decided' | 'version_published';

/** What one side did to the base at a pointer. */
export type SyncChangeKind = 'addition' | 'update' | 'deletion';

/** The two sides a conflict can be settled towards. */
export type SyncResolution = 'git' | 'draft';

/** One incoming change the merge would apply, as apiome-rest returns it. */
export interface SyncChange {
  pointer: string;
  kind: SyncChangeKind;
  scope: string;
  group: string;
  label: string;
  before?: unknown;
  after?: unknown;
  source_file?: string;
  source_line?: number | null;
}

/** One overlap the merge could not decide, as apiome-rest returns it. */
export interface SyncConflict {
  id: string;
  plan_id: string;
  pointer: string;
  scope: string;
  group_key: string;
  label: string;
  git_kind: SyncChangeKind;
  draft_kind: SyncChangeKind;
  base_value?: unknown;
  git_value?: unknown;
  draft_value?: unknown;
  source_file?: string;
  source_line?: number | null;
  source_url?: string;
  resolution?: SyncResolution | null;
  resolved_at?: string | null;
  resolved_by_name?: string | null;
  resolution_note?: string | null;
  created_at: string;
}

/** One stored merge result, as apiome-rest returns it. */
export interface SyncPlan {
  id: string;
  binding_id: string;
  version_id: string;
  candidate_id?: string | null;
  base_commit_sha: string;
  base_digest: string;
  git_commit_sha: string;
  git_digest: string;
  draft_digest: string;
  plan_fingerprint: string;
  status: SyncPlanStatus;
  auto_applied_count: number;
  local_count: number;
  agreed_count: number;
  conflict_count: number;
  unresolved_count: number;
  conflicts_truncated?: boolean;
  changes: SyncChange[];
  source_file?: string;
  source_member_count?: number;
  guard: SyncGuard;
  stale?: boolean;
  computed_by_name?: string | null;
  created_at: string;
  updated_at: string;
}

/** A merge result with its conflicts. */
export interface SyncPlanDetail {
  plan: SyncPlan;
  conflicts: SyncConflict[];
}

/** Where one version stands with respect to merging its repository ref. */
export interface VersionSyncStatus {
  version_id: string;
  version_label?: string | null;
  bound: boolean;
  latest: SyncPlanDetail | null;
  history: SyncPlan[];
}

/** What the panel sends to compute a merge. */
export interface ComputeRequest {
  candidate_id?: string;
  refresh?: boolean;
}

/**
 * The only fields a browser may put in a compute request.
 *
 * A credential is deliberately absent, as it is for binding: apiome-rest reads both commits with a
 * **stored** linked-account token and rejects an unknown field outright, so forwarding a body
 * wholesale would turn a hand-made request into a 422 the panel cannot explain.
 */
export const COMPUTE_REQUEST_FIELDS = ['candidate_id', 'refresh'] as const;

/** The only fields a browser may put in a settle request. */
export const RESOLVE_REQUEST_FIELDS = ['resolution', 'note'] as const;

/** The two sides a person may choose. */
export const RESOLUTIONS: readonly SyncResolution[] = ['git', 'draft'];

/** How many characters of a commit sha are shown. Matches `@lib/draft-bindings`. */
export const SHORT_SHA_LENGTH = 7;

/** The longest rendering of a conflict value shown inline before it is elided. */
export const VALUE_PREVIEW_LENGTH = 400;

/** What each merge status is called on screen. */
export const SYNC_STATUS_LABEL: Record<SyncPlanStatus, string> = {
  clean: 'Nothing to merge',
  mergeable: 'Merges cleanly',
  conflicted: 'Conflicts',
  resolved: 'Conflicts settled',
};

/** The Badge tone each merge status is drawn in. */
export const SYNC_STATUS_TONE: Record<SyncPlanStatus, string> = {
  clean: 'secondary',
  mergeable: 'success',
  conflicted: 'warning',
  resolved: 'success',
};

/** What each change kind is called on screen. */
export const SYNC_KIND_LABEL: Record<SyncChangeKind, string> = {
  addition: 'Added',
  update: 'Changed',
  deletion: 'Removed',
};

/** What each side of a conflict is called on screen. */
export const SYNC_SIDE_LABEL: Record<'base' | SyncResolution, string> = {
  base: 'Last synchronized',
  git: 'In the repository',
  draft: 'In this draft',
};

/**
 * Why a merge result may not become an edit, in the reader's terms.
 *
 * `none` has no sentence: an ordinary draft needs no explanation, and inventing one would make
 * every merge look like it had a caveat.
 */
export const SYNC_GUARD_SENTENCE: Record<SyncGuard, string | null> = {
  none: null,
  review_decided:
    'A reviewer has already recorded a decision on this version. Applying these changes would ' +
    'invalidate it, so settle the review first.',
  version_published:
    'This version is published, so it is no longer a draft. The merge below is for reference.',
};

/** apiome-rest's stable refusal codes, in the reader's terms. */
export const SYNC_ERROR_MESSAGE: Record<string, string> = {
  'sync-not-bound': 'This version is not bound to a branch, so there is nothing to merge against.',
  'sync-nothing-to-merge':
    'The branch is exactly where this draft was last synchronized. Check for updates first.',
  'sync-base-drifted':
    'The commit this draft was synchronized with no longer holds the same files — the branch was ' +
    'rewritten. Check for updates, and re-bind if the history really moved.',
  'sync-invalid-document':
    'One of the three documents could not be read as a spec. Narrow the source path to the ' +
    'document you want merged.',
  'sync-plan-not-found': 'That merge result is no longer here.',
  'sync-conflict-not-found': 'That conflict is no longer here.',
  'sync-conflict-resolved': 'Somebody already settled that conflict. Settlements are final.',
  'sync-conflict': 'Somebody else changed this while you were deciding. Reload and try again.',
  'binding-repository-forbidden':
    'The stored credential cannot read that repository any more. Re-link the account, or bind to ' +
    'a repository it can reach.',
  'binding-repository-not-found': 'That repository or commit is no longer there.',
  'binding-repository-unreachable': 'The provider could not be reached. Try again in a moment.',
};

/**
 * Keep only the fields apiome-rest accepts when computing a merge.
 *
 * @param body - Whatever the browser sent.
 * @returns The forwardable subset; `refresh` is kept only when it is really `true`.
 */
export function sanitizeComputeRequest(body: unknown): ComputeRequest {
  const source = (body ?? {}) as Record<string, unknown>;
  const request: ComputeRequest = {};
  const candidate = source.candidate_id;
  if (typeof candidate === 'string' && candidate.trim()) request.candidate_id = candidate.trim();
  if (source.refresh === true) request.refresh = true;
  return request;
}

/**
 * Keep only the fields apiome-rest accepts when settling a conflict.
 *
 * An unknown `resolution` is dropped rather than passed on, so a hand-made request is refused here
 * with a sentence the panel can show instead of a 422 it cannot explain.
 *
 * @param body - Whatever the browser sent.
 * @returns The forwardable subset, or null when no valid side was named.
 */
export function sanitizeResolveRequest(
  body: unknown
): { resolution: SyncResolution; note?: string } | null {
  const source = (body ?? {}) as Record<string, unknown>;
  const resolution = source.resolution;
  if (typeof resolution !== 'string' || !RESOLUTIONS.includes(resolution as SyncResolution)) {
    return null;
  }
  const note = source.note;
  const request: { resolution: SyncResolution; note?: string } = {
    resolution: resolution as SyncResolution,
  };
  if (typeof note === 'string' && note.trim()) request.note = note.trim();
  return request;
}

/**
 * The first characters of a commit sha, for a line a person reads.
 *
 * @param sha - The full sha.
 * @returns Its short form, or an empty string.
 */
export function shortSha(sha: string | null | undefined): string {
  return (sha ?? '').slice(0, SHORT_SHA_LENGTH);
}

/**
 * One line saying what a merge found.
 *
 * @param plan - The merge result.
 * @returns A sentence fit to show under the status badge.
 */
export function planSentence(plan: SyncPlan): string {
  if (plan.status === 'clean') {
    return `Nothing changed in the repository between ${shortSha(plan.base_commit_sha)} and ${shortSha(
      plan.git_commit_sha
    )}.`;
  }
  const applied = `${plan.auto_applied_count} ${plan.auto_applied_count === 1 ? 'change' : 'changes'}`;
  if (plan.conflict_count === 0) {
    return `${applied} from ${shortSha(plan.git_commit_sha)} would apply cleanly.`;
  }
  const outstanding = plan.unresolved_count;
  const collisions = `${plan.conflict_count} ${plan.conflict_count === 1 ? 'conflict' : 'conflicts'}`;
  if (outstanding === 0) {
    return `${applied} would apply; all ${collisions} have been settled.`;
  }
  // "at least", not a count, when the merge found more than one plan stores: claiming an exact
  // number that is really a page of a longer list is the one way this sentence could mislead.
  const found = plan.conflicts_truncated ? `at least ${collisions}` : collisions;
  return `${applied} would apply; ${outstanding} of ${found} still need a decision.`;
}

/**
 * One line saying where a conflict is.
 *
 * @param conflict - The conflict.
 * @returns `"spec/openapi.yaml:42"`, or just the file, or an empty string when neither is known.
 */
export function conflictLocation(conflict: SyncConflict): string {
  const file = (conflict.source_file ?? '').trim();
  if (!file) return '';
  return conflict.source_line ? `${file}:${conflict.source_line}` : file;
}

/**
 * Render one side of a conflict for display.
 *
 * A JSON value is shown as compact JSON rather than as a string, because `"1.0.0"` and `1.0.0` are
 * different values and a conflict is exactly where that difference matters. An absent side — which
 * a deletion has — is named rather than drawn as `null`, which is itself a legal value.
 *
 * @param value - The stored value.
 * @param kind - What that side did to the base, which is what says whether the value is absent.
 * @param side - Which side it is, for the absence sentence.
 * @returns The text to show.
 */
export function formatConflictValue(
  value: unknown,
  kind: SyncChangeKind,
  side: 'base' | SyncResolution
): string {
  if (kind === 'deletion' && side !== 'base') return 'removed';
  if (kind === 'addition' && side === 'base') return 'not present';
  if (isTruncated(value)) return 'too large to show here';
  let text: string;
  try {
    text = JSON.stringify(value, null, 2) ?? 'null';
  } catch {
    return 'could not be displayed';
  }
  return text.length > VALUE_PREVIEW_LENGTH ? `${text.slice(0, VALUE_PREVIEW_LENGTH)}…` : text;
}

/**
 * Whether apiome-rest replaced a value with its size because it was too large to store inline.
 *
 * @param value - The stored value.
 * @returns True for the truncation marker.
 */
export function isTruncated(value: unknown): boolean {
  return Boolean(
    value && typeof value === 'object' && (value as { $truncated?: unknown }).$truncated === true
  );
}

/**
 * The sentence to show for a failed request.
 *
 * @param code - apiome-rest's stable code, when it sent one.
 * @param fallback - The message it sent, used when the code is not one this panel explains.
 * @returns What to show.
 */
export function syncErrorMessage(
  code: string | null | undefined,
  fallback: string
): string {
  return (code && SYNC_ERROR_MESSAGE[code]) || fallback;
}
