/**
 * The framework-free half of three-way spec synchronization (GNC-2.3, #4739).
 *
 * `@lib/spec-sync` is shared by the Synchronization section and by its BFF routes, so every rule
 * below is asserted directly rather than through a rendered tree:
 *
 *   1. **A browser may ask for exactly two things**, and a credential is not one of them — the same
 *      whitelist discipline `@lib/draft-bindings` applies to a bind request.
 *   2. **A conflict is settled towards one of two sides, or not at all.** An unknown side is
 *      dropped here, so a hand-made request is refused with a sentence rather than a 422.
 *   3. **A value is shown as what it is.** `"1.0.0"` and `1.0.0` are different values, and a
 *      conflict is exactly where that difference matters; an absent side is named, because `null`
 *      is itself a legal value.
 *   4. **Every sentence says that nothing happened to the draft** — "would apply", never "applied".
 */

import {
  COMPUTE_REQUEST_FIELDS,
  RESOLUTIONS,
  RESOLVE_REQUEST_FIELDS,
  SYNC_GUARD_SENTENCE,
  SYNC_STATUS_LABEL,
  SYNC_STATUS_TONE,
  VALUE_PREVIEW_LENGTH,
  conflictLocation,
  formatConflictValue,
  isTruncated,
  planSentence,
  sanitizeComputeRequest,
  sanitizeResolveRequest,
  shortSha,
  syncErrorMessage,
  type SyncConflict,
  type SyncPlan,
} from '@lib/spec-sync';

const COMMIT_BASE = '1'.repeat(40);
const COMMIT_NEXT = '2'.repeat(40);

/** A merge result with the fields the sentences read. */
function plan(overrides: Partial<SyncPlan> = {}): SyncPlan {
  return {
    id: 'p1',
    binding_id: 'b1',
    version_id: 'v1',
    base_commit_sha: COMMIT_BASE,
    base_digest: 'sha256:base',
    git_commit_sha: COMMIT_NEXT,
    git_digest: 'sha256:git',
    draft_digest: 'sha256:draft',
    plan_fingerprint: 'sha256:plan',
    status: 'mergeable',
    auto_applied_count: 2,
    local_count: 0,
    agreed_count: 0,
    conflict_count: 0,
    unresolved_count: 0,
    changes: [],
    guard: 'none',
    created_at: '2026-09-16T12:00:00Z',
    updated_at: '2026-09-16T12:00:00Z',
    ...overrides,
  };
}

/** A conflict with the fields the renderings read. */
function conflict(overrides: Partial<SyncConflict> = {}): SyncConflict {
  return {
    id: 'c1',
    plan_id: 'p1',
    pointer: '/info/version',
    scope: 'document',
    group_key: 'info',
    label: 'Changed /info/version',
    git_kind: 'update',
    draft_kind: 'update',
    base_value: '1.0.0',
    git_value: '2.0.0',
    draft_value: '1.5.0',
    source_file: 'spec/openapi.yaml',
    source_line: 4,
    source_url: 'https://github.com/acme/specs/blob/abc/spec/openapi.yaml#L4',
    resolution: null,
    created_at: '2026-09-16T12:00:00Z',
    ...overrides,
  };
}

describe('what a browser may ask for', () => {
  it('forwards only the two fields apiome-rest accepts on a merge', () => {
    expect([...COMPUTE_REQUEST_FIELDS]).toEqual(['candidate_id', 'refresh']);
    expect(
      sanitizeComputeRequest({ candidate_id: ' c1 ', refresh: true, token: 'ghp_secret' })
    ).toEqual({ candidate_id: 'c1', refresh: true });
  });

  it('never lets a credential through, whatever it is called', () => {
    for (const field of ['token', 'access_token', 'password', 'authorization']) {
      expect(sanitizeComputeRequest({ [field]: 'ghp_secret' })).toEqual({});
    }
  });

  it('keeps refresh only when it is really true', () => {
    for (const value of ['true', 1, {}, null, false]) {
      expect(sanitizeComputeRequest({ refresh: value })).toEqual({});
    }
  });

  it('drops a blank or absent candidate rather than sending one', () => {
    expect(sanitizeComputeRequest({ candidate_id: '   ' })).toEqual({});
    expect(sanitizeComputeRequest({})).toEqual({});
    expect(sanitizeComputeRequest(null)).toEqual({});
  });
});

describe('settling a conflict', () => {
  it('accepts exactly the two sides', () => {
    expect([...RESOLUTIONS]).toEqual(['git', 'draft']);
    expect([...RESOLVE_REQUEST_FIELDS]).toEqual(['resolution', 'note']);
    for (const resolution of RESOLUTIONS) {
      expect(sanitizeResolveRequest({ resolution })).toEqual({ resolution });
    }
  });

  it('refuses any third option here rather than forwarding it', () => {
    for (const resolution of ['custom', 'mine', '', 'GIT', null, 7]) {
      expect(sanitizeResolveRequest({ resolution })).toBeNull();
    }
    expect(sanitizeResolveRequest({})).toBeNull();
  });

  it('keeps a note, trimmed, and drops a blank one', () => {
    expect(sanitizeResolveRequest({ resolution: 'git', note: '  agreed in review  ' })).toEqual({
      resolution: 'git',
      note: 'agreed in review',
    });
    expect(sanitizeResolveRequest({ resolution: 'git', note: '   ' })).toEqual({
      resolution: 'git',
    });
  });

  it('forwards nothing else from the body', () => {
    expect(sanitizeResolveRequest({ resolution: 'draft', plan_id: 'other', token: 'x' })).toEqual({
      resolution: 'draft',
    });
  });
});

describe('what a merge found, in a sentence', () => {
  it('says nothing changed for a clean merge', () => {
    expect(planSentence(plan({ status: 'clean', auto_applied_count: 0 }))).toBe(
      'Nothing changed in the repository between 1111111 and 2222222.'
    );
  });

  it('says changes *would* apply, because nothing has happened to the draft', () => {
    const sentence = planSentence(plan());
    expect(sentence).toBe('2 changes from 2222222 would apply cleanly.');
    expect(sentence).not.toMatch(/\bapplied\b/);
  });

  it('counts one change in the singular', () => {
    expect(planSentence(plan({ auto_applied_count: 1 }))).toContain('1 change from');
  });

  it('says how many collisions still need a decision', () => {
    expect(
      planSentence(plan({ status: 'conflicted', conflict_count: 3, unresolved_count: 2 }))
    ).toBe('2 changes would apply; 2 of 3 conflicts still need a decision.');
  });

  it('says so when every collision has been settled', () => {
    expect(
      planSentence(plan({ status: 'resolved', conflict_count: 1, unresolved_count: 0 }))
    ).toBe('2 changes would apply; all 1 conflict have been settled.');
  });

  it('says "at least" when the merge found more collisions than it could store', () => {
    // Claiming an exact number that is really a page of a longer list is the one way this sentence
    // could mislead a reader into thinking they are nearly done.
    expect(
      planSentence(
        plan({ status: 'conflicted', conflict_count: 200, unresolved_count: 200, conflicts_truncated: true })
      )
    ).toBe('2 changes would apply; 200 of at least 200 conflicts still need a decision.');
  });

  it('never claims a draft was changed, in any status', () => {
    for (const status of ['clean', 'mergeable', 'conflicted', 'resolved'] as const) {
      expect(planSentence(plan({ status, conflict_count: status === 'clean' ? 0 : 1, unresolved_count: status === 'conflicted' ? 1 : 0 }))).not.toMatch(
        /updated|overwritten|rewritten|applied to/i
      );
    }
  });
});

describe('the four statuses and the two guards', () => {
  it('names and tones every status', () => {
    for (const status of ['clean', 'mergeable', 'conflicted', 'resolved'] as const) {
      expect(SYNC_STATUS_LABEL[status]).toBeTruthy();
      expect(SYNC_STATUS_TONE[status]).toBeTruthy();
    }
    // Only a collision is drawn as something to act on.
    expect(SYNC_STATUS_TONE.conflicted).toBe('warning');
    expect(SYNC_STATUS_TONE.mergeable).toBe('success');
  });

  it('explains a guard and says nothing at all for an ordinary draft', () => {
    expect(SYNC_GUARD_SENTENCE.none).toBeNull();
    expect(SYNC_GUARD_SENTENCE.review_decided).toContain('reviewer');
    expect(SYNC_GUARD_SENTENCE.version_published).toContain('published');
  });
});

describe('showing a conflict', () => {
  it('locates it in the repository file and line', () => {
    expect(conflictLocation(conflict())).toBe('spec/openapi.yaml:4');
    expect(conflictLocation(conflict({ source_line: null }))).toBe('spec/openapi.yaml');
    expect(conflictLocation(conflict({ source_file: '' }))).toBe('');
  });

  it('shows a value as JSON, so a quoted number is not mistaken for a number', () => {
    expect(formatConflictValue('1.0.0', 'update', 'git')).toBe('"1.0.0"');
    expect(formatConflictValue(1, 'update', 'git')).toBe('1');
    expect(formatConflictValue(null, 'update', 'git')).toBe('null');
    expect(formatConflictValue(false, 'update', 'draft')).toBe('false');
  });

  it('names an absent side rather than drawing it as null', () => {
    expect(formatConflictValue(null, 'deletion', 'draft')).toBe('removed');
    expect(formatConflictValue(null, 'deletion', 'git')).toBe('removed');
    expect(formatConflictValue(null, 'addition', 'base')).toBe('not present');
    // A deletion's *base* side is the value that was there, and is shown.
    expect(formatConflictValue('1.0.0', 'deletion', 'base')).toBe('"1.0.0"');
  });

  it('says so when apiome-rest replaced a value with its size', () => {
    const marker = { $truncated: true, bytes: 40000 };
    expect(isTruncated(marker)).toBe(true);
    expect(isTruncated({ type: 'object' })).toBe(false);
    expect(isTruncated(null)).toBe(false);
    expect(formatConflictValue(marker, 'update', 'git')).toBe('too large to show here');
  });

  it('elides a long value rather than filling the panel with it', () => {
    const shown = formatConflictValue({ description: 'x'.repeat(2000) }, 'update', 'git');
    expect(shown.length).toBeLessThanOrEqual(VALUE_PREVIEW_LENGTH + 1);
    expect(shown.endsWith('…')).toBe(true);
  });
});

describe('what a refusal says', () => {
  it('turns every stable code into something a reader can act on', () => {
    for (const code of [
      'sync-not-bound',
      'sync-nothing-to-merge',
      'sync-base-drifted',
      'sync-invalid-document',
      'sync-conflict-resolved',
      'sync-conflict',
      'binding-repository-forbidden',
    ]) {
      const message = syncErrorMessage(code, 'fallback');
      expect(message).not.toBe('fallback');
      expect(message.length).toBeGreaterThan(20);
    }
  });

  it('falls back to what apiome-rest said for a code it does not explain', () => {
    expect(syncErrorMessage('sync-something-new', 'the server said this')).toBe(
      'the server said this'
    );
    expect(syncErrorMessage(null, 'the server said this')).toBe('the server said this');
  });

  it('tells a reader what to do about a rewritten merge base', () => {
    expect(syncErrorMessage('sync-base-drifted', '')).toContain('Check for updates');
  });
});

describe('shas', () => {
  it('shortens a sha for a line a person reads', () => {
    expect(shortSha(COMMIT_BASE)).toBe('1111111');
    expect(shortSha(null)).toBe('');
    expect(shortSha(undefined)).toBe('');
  });
});
