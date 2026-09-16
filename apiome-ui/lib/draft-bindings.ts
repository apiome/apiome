/**
 * Branch-to-draft binding rules, framework-free — GNC-2.1 (#4737).
 *
 * The Repository panel on the Versions screen and its BFF routes share this file: the wire shapes
 * apiome-rest answers with, the whitelist of what a browser may ask for, and the sentences and
 * tones a binding and its sync candidates are drawn with.
 *
 * Nothing here touches React, `fetch`, or the DOM, so every rule below is asserted directly.
 */

/** How a sync candidate was raised. Mirrors apiome-rest's `app.draft_bindings`. */
export type CandidateOrigin = 'webhook' | 'manual' | 'sweep';

/** Where a sync candidate stands. Mirrors apiome-rest's `app.draft_bindings`. */
export type CandidateStatus = 'pending' | 'applied' | 'dismissed' | 'superseded';

/** Why an active binding stopped being one. */
export type ReleaseReason = 'replaced' | 'unbound' | 'repository_removed';

/** The two settlements a person may record; `superseded` is the system's alone. */
export type ResolvableStatus = 'applied' | 'dismissed';

/** One binding row, as apiome-rest returns it. */
export interface DraftBinding {
  id: string;
  version_id: string;
  version_label?: string | null;
  repository_id?: string | null;
  provider: string;
  repo_full_name: string;
  repo_url: string;
  ref: string;
  path: string;
  commit_sha: string;
  source_digest: string;
  synchronized_at: string;
  browse_url?: string | null;
  active: boolean;
  created_by_name?: string | null;
  created_at: string;
  updated_at: string;
  released_at?: string | null;
  release_reason?: ReleaseReason | null;
  pending_candidate_count: number;
}

/** One observed movement of a bound ref, as apiome-rest returns it. */
export interface SyncCandidate {
  id: string;
  binding_id: string;
  ref: string;
  from_commit_sha: string;
  from_digest: string;
  to_commit_sha: string;
  to_digest?: string | null;
  origin: CandidateOrigin;
  delivery_id?: string | null;
  status: CandidateStatus;
  detected_at: string;
  detected_by_name?: string | null;
  resolved_at?: string | null;
  resolved_by_name?: string | null;
  resolution_note?: string | null;
}

/** A binding with what is outstanding on it and what has settled. */
export interface DraftBindingDetail {
  binding: DraftBinding;
  pending: SyncCandidate[];
  history: SyncCandidate[];
}

/** Where one version stands with respect to a repository. */
export interface VersionBindingStatus {
  version_id: string;
  version_label?: string | null;
  published: boolean;
  bound: boolean;
  binding: DraftBindingDetail | null;
  released: DraftBinding[];
}

/** What the panel sends to bind a draft. */
export interface BindRequest {
  repository_id?: string;
  repo_url?: string;
  ref?: string;
  path?: string;
  replace?: boolean;
}

/**
 * The only fields a browser may put in a bind request.
 *
 * A credential is deliberately absent: apiome-rest reads a private repository with a **stored**
 * linked-account token and rejects an unknown field outright, so forwarding a body wholesale would
 * turn a hand-made request into a 422 the panel cannot explain. `linked_account_id` is a reference
 * to the caller's own stored account, never a secret.
 */
export const BIND_REQUEST_FIELDS = [
  'repository_id',
  'repo_url',
  'ref',
  'path',
  'linked_account_id',
  'replace',
] as const;

/** The settlements the panel may ask for. */
export const RESOLVABLE_STATUSES: readonly ResolvableStatus[] = ['applied', 'dismissed'];

/** How many characters of a commit sha are shown. */
export const SHORT_SHA_LENGTH = 7;

/**
 * Keep only the fields apiome-rest accepts on a bind, dropping blanks.
 *
 * @param body - Whatever the browser sent.
 * @returns The forwardable subset; `replace` is kept only when it is really `true`.
 */
export function sanitizeBindRequest(body: unknown): Record<string, unknown> {
  const source = (body ?? {}) as Record<string, unknown>;
  const cleaned: Record<string, unknown> = {};
  for (const field of BIND_REQUEST_FIELDS) {
    const value = source[field];
    if (field === 'replace') {
      if (value === true) cleaned.replace = true;
      continue;
    }
    if (typeof value === 'string' && value.trim()) cleaned[field] = value.trim();
  }
  return cleaned;
}

/**
 * Keep only the fields apiome-rest accepts when settling a candidate.
 *
 * @param body - Whatever the browser sent.
 * @returns `{status, note?}`, or null when the status is not one a person may record.
 */
export function sanitizeResolveRequest(body: unknown): { status: ResolvableStatus; note?: string } | null {
  const source = (body ?? {}) as Record<string, unknown>;
  const status = source.status;
  if (typeof status !== 'string' || !RESOLVABLE_STATUSES.includes(status as ResolvableStatus)) {
    return null;
  }
  const note = source.note;
  const cleaned: { status: ResolvableStatus; note?: string } = { status: status as ResolvableStatus };
  if (typeof note === 'string' && note.trim()) cleaned.note = note.trim();
  return cleaned;
}

/**
 * A commit sha in the form it is shown in.
 *
 * @param sha - The full sha, or anything shorter.
 * @returns The first {@link SHORT_SHA_LENGTH} characters, or `''`.
 */
export function shortSha(sha: string | null | undefined): string {
  return (sha ?? '').trim().slice(0, SHORT_SHA_LENGTH);
}

/**
 * What a binding is bound to, in one line.
 *
 * @param binding - The binding.
 * @returns e.g. `acme/specs @ main · spec/openapi.yaml`, with the path dropped when it is the
 *   whole tree.
 */
export function bindingSummary(binding: DraftBinding): string {
  const head = `${binding.repo_full_name} @ ${binding.ref}`;
  return binding.path ? `${head} · ${binding.path}` : head;
}

/** A binding's state, as the panel groups it. */
export type BindingState = 'active' | 'outdated' | 'released' | 'unusable';

/**
 * Where a binding stands, for the badge and the tone.
 *
 * "Unusable" is a binding whose repository registration is gone: it is still history, but nothing
 * can read from it again, and saying only "released" would hide why.
 *
 * @param binding - The binding.
 * @returns Its state.
 */
export function bindingState(binding: DraftBinding): BindingState {
  if (!binding.active) {
    return binding.release_reason === 'repository_removed' ? 'unusable' : 'released';
  }
  return binding.pending_candidate_count > 0 ? 'outdated' : 'active';
}

/** The visual tone each binding state is drawn in; the class names live in `globals.css`. */
export const BINDING_STATE_TONE: Record<BindingState, string> = {
  active: 'success',
  outdated: 'warning',
  released: 'neutral',
  unusable: 'danger',
};

/** The words each binding state is labelled with. */
export const BINDING_STATE_LABEL: Record<BindingState, string> = {
  active: 'In sync',
  outdated: 'Update available',
  released: 'Released',
  unusable: 'Repository removed',
};

/** The words each candidate status is labelled with. */
export const CANDIDATE_STATUS_LABEL: Record<CandidateStatus, string> = {
  pending: 'Awaiting decision',
  applied: 'Applied',
  dismissed: 'Dismissed',
  superseded: 'Superseded',
};

/** The visual tone each candidate status is drawn in. */
export const CANDIDATE_STATUS_TONE: Record<CandidateStatus, string> = {
  pending: 'warning',
  applied: 'success',
  dismissed: 'neutral',
  superseded: 'neutral',
};

/** How each origin is described in a candidate's sentence. */
export const CANDIDATE_ORIGIN_LABEL: Record<CandidateOrigin, string> = {
  webhook: 'a push',
  manual: 'a check',
  sweep: 'the refresh sweep',
};

/**
 * What a sync candidate says it observed.
 *
 * @param candidate - The candidate.
 * @returns e.g. `a push moved main from 1111111 to 2222222`.
 */
export function candidateSentence(candidate: SyncCandidate): string {
  const origin = CANDIDATE_ORIGIN_LABEL[candidate.origin] ?? 'an update';
  return (
    `${origin} moved ${candidate.ref} from ${shortSha(candidate.from_commit_sha)} ` +
    `to ${shortSha(candidate.to_commit_sha)}`
  );
}

/**
 * Whether the content behind a candidate is known to differ from the binding's.
 *
 * A candidate raised by a webhook names a commit and nothing more, so the answer is `null` — not
 * `false` — until somebody reads that commit. Saying "no change" there would be a claim nobody
 * has checked.
 *
 * @param candidate - The candidate.
 * @returns True when the digests differ, false when they match, null when it is not yet known.
 */
export function candidateContentChanged(candidate: SyncCandidate): boolean | null {
  if (!candidate.to_digest) return null;
  return candidate.to_digest !== candidate.from_digest;
}

/**
 * The message to show for a refusal from the binding API.
 *
 * The stable `binding-*` codes are turned into something a reader can act on; anything else falls
 * back to what the server said.
 *
 * @param code - apiome-rest's refusal code, when it sent one.
 * @param fallback - The server's message.
 * @returns What to show.
 */
export function bindingErrorMessage(code: string | null | undefined, fallback: string): string {
  switch (code) {
    case 'binding-version-published':
      return 'Only a draft version can be bound to a branch.';
    case 'binding-already-bound':
      return 'This version is already bound. Release it first, or choose Replace.';
    case 'binding-repository-forbidden':
      return 'The stored credential cannot read that repository. Link an account with access and try again.';
    case 'binding-repository-not-found':
      return 'That repository, branch, or path could not be found.';
    case 'binding-repository-unreachable':
      return 'The repository host could not be reached. Try again in a moment.';
    case 'binding-invalid-source':
      return 'That selection does not resolve to any importable files.';
    case 'binding-unchanged':
      return 'The branch is still at the commit this draft is bound to.';
    case 'binding-candidate-resolved':
      return 'That update has already been decided.';
    case 'binding-not-found':
      return 'This version is not bound to a repository.';
    case 'binding-conflict':
      return 'Somebody changed this binding at the same time. Reload and try again.';
    default:
      return fallback;
  }
}
