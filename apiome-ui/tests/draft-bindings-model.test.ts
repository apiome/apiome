/**
 * The binding rules, framework-free (GNC-2.1, #4737).
 *
 * `@lib/draft-bindings` is shared by the Repository panel and the BFF routes, so every rule below
 * is asserted directly rather than through a rendered screen: what a browser may send, how a
 * binding and its sync candidates are described, and — the one that matters most — that "the
 * content did not change" is never claimed about a commit nobody has read.
 */

import { describe, expect, test } from '@jest/globals';

import {
  BINDING_STATE_LABEL,
  BINDING_STATE_TONE,
  CANDIDATE_STATUS_LABEL,
  CANDIDATE_STATUS_TONE,
  bindingErrorMessage,
  bindingState,
  bindingSummary,
  candidateContentChanged,
  candidateSentence,
  sanitizeBindRequest,
  sanitizeResolveRequest,
  shortSha,
  type DraftBinding,
  type SyncCandidate,
} from '@lib/draft-bindings';

const COMMIT_ONE = '1'.repeat(40);
const COMMIT_TWO = '2'.repeat(40);

/**
 * A binding, with the fields a test cares about overridden.
 *
 * @param overrides - What to change.
 * @returns The binding.
 */
function binding(overrides: Partial<DraftBinding> = {}): DraftBinding {
  return {
    id: 'b1',
    version_id: 'v1',
    repository_id: 'r1',
    provider: 'github',
    repo_full_name: 'acme/specs',
    repo_url: 'https://github.com/acme/specs',
    ref: 'main',
    path: 'spec/openapi.yaml',
    commit_sha: COMMIT_ONE,
    source_digest: 'sha256:one',
    synchronized_at: '2026-09-16T10:00:00Z',
    active: true,
    created_at: '2026-09-16T10:00:00Z',
    updated_at: '2026-09-16T10:00:00Z',
    pending_candidate_count: 0,
    ...overrides,
  };
}

/**
 * A sync candidate, with the fields a test cares about overridden.
 *
 * @param overrides - What to change.
 * @returns The candidate.
 */
function candidate(overrides: Partial<SyncCandidate> = {}): SyncCandidate {
  return {
    id: 'c1',
    binding_id: 'b1',
    ref: 'main',
    from_commit_sha: COMMIT_ONE,
    from_digest: 'sha256:one',
    to_commit_sha: COMMIT_TWO,
    origin: 'webhook',
    status: 'pending',
    detected_at: '2026-09-16T11:00:00Z',
    ...overrides,
  };
}

describe('what a browser may send', () => {
  test('keeps the whitelist and drops everything else', () => {
    expect(
      sanitizeBindRequest({
        repository_id: 'r1',
        repo_url: 'https://github.com/acme/specs',
        ref: ' main ',
        path: 'spec',
        linked_account_id: 'la1',
        replace: true,
        token: 'ghp_secret',
        version: 'not-yours-to-say',
      })
    ).toEqual({
      repository_id: 'r1',
      repo_url: 'https://github.com/acme/specs',
      ref: 'main',
      path: 'spec',
      linked_account_id: 'la1',
      replace: true,
    });
  });

  test('drops blanks and a non-boolean replace', () => {
    expect(sanitizeBindRequest({ repository_id: '   ', ref: '', replace: 'true' })).toEqual({});
    expect(sanitizeBindRequest(null)).toEqual({});
  });

  test('only the two settlements a person records are accepted', () => {
    expect(sanitizeResolveRequest({ status: 'applied' })).toEqual({ status: 'applied' });
    expect(sanitizeResolveRequest({ status: 'dismissed', note: ' why ' })).toEqual({
      status: 'dismissed',
      note: 'why',
    });
    // `superseded` is what the system records when a newer update replaces an older one.
    expect(sanitizeResolveRequest({ status: 'superseded' })).toBeNull();
    expect(sanitizeResolveRequest({ status: 'pending' })).toBeNull();
    expect(sanitizeResolveRequest({})).toBeNull();
  });
});

describe('how a binding reads', () => {
  test('names its repository, ref and path', () => {
    expect(bindingSummary(binding())).toBe('acme/specs @ main · spec/openapi.yaml');
    expect(bindingSummary(binding({ path: '' }))).toBe('acme/specs @ main');
  });

  test('shortens a commit to seven characters', () => {
    expect(shortSha(COMMIT_ONE)).toBe('1111111');
    expect(shortSha(null)).toBe('');
  });

  test.each([
    ['active', binding()],
    ['outdated', binding({ pending_candidate_count: 1 })],
    ['released', binding({ active: false, release_reason: 'unbound' })],
    ['released', binding({ active: false, release_reason: 'replaced' })],
    ['unusable', binding({ active: false, release_reason: 'repository_removed' })],
  ])('reads as %s', (state, row) => {
    expect(bindingState(row)).toBe(state);
  });

  test('every state has a tone and a label', () => {
    for (const state of ['active', 'outdated', 'released', 'unusable'] as const) {
      expect(BINDING_STATE_TONE[state]).toBeTruthy();
      expect(BINDING_STATE_LABEL[state]).toBeTruthy();
    }
  });
});

describe('how a sync candidate reads', () => {
  test('says what moved, from where, to where', () => {
    expect(candidateSentence(candidate())).toBe('a push moved main from 1111111 to 2222222');
    expect(candidateSentence(candidate({ origin: 'manual' }))).toContain('a check moved');
    expect(candidateSentence(candidate({ origin: 'sweep' }))).toContain('the refresh sweep moved');
  });

  test('never claims the content is unchanged for a commit nobody has read', () => {
    // A webhook names a commit and nothing more, so the honest answer is "not known".
    expect(candidateContentChanged(candidate())).toBeNull();
    expect(candidateContentChanged(candidate({ to_digest: 'sha256:two' }))).toBe(true);
    expect(candidateContentChanged(candidate({ to_digest: 'sha256:one' }))).toBe(false);
  });

  test('every status has a tone and a label', () => {
    for (const status of ['pending', 'applied', 'dismissed', 'superseded'] as const) {
      expect(CANDIDATE_STATUS_TONE[status]).toBeTruthy();
      expect(CANDIDATE_STATUS_LABEL[status]).toBeTruthy();
    }
  });
});

describe('what a refusal says', () => {
  test.each([
    'binding-version-published',
    'binding-already-bound',
    'binding-repository-forbidden',
    'binding-repository-not-found',
    'binding-repository-unreachable',
    'binding-invalid-source',
    'binding-unchanged',
    'binding-candidate-resolved',
    'binding-not-found',
    'binding-conflict',
  ])('%s is turned into something actionable', (code) => {
    const message = bindingErrorMessage(code, 'server said');
    expect(message).not.toBe('server said');
    expect(message.endsWith('.')).toBe(true);
  });

  test('an unknown code keeps what the server said', () => {
    expect(bindingErrorMessage('binding-brand-new', 'server said')).toBe('server said');
    expect(bindingErrorMessage(null, 'server said')).toBe('server said');
  });
});
