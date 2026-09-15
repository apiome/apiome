/**
 * The review page's rules (COL-2.2, #4518).
 *
 * `lib/review-page.ts` is framework-free, so its rules are pinned here without a DOM: the tab
 * vocabulary, the header's badge and tally, the decision bar's modes (which must follow
 * apiome-rest's refusals so the bar never offers a button the API refuses), the required note on
 * Request changes, the refusal messages, the live classified diff's grouping (mirroring apiome-rest's
 * `path_group_for_pointer`), and the baseline rule.
 */

import {
  DECISION_LABELS,
  REVIEW_ERROR_MESSAGES,
  REVIEW_NOTE_MAX_LENGTH,
  REVIEW_TABS,
  changeCountText,
  classifiedChangeSummary,
  classifiedChangesToEntries,
  decisionBadgeVariant,
  decisionBarModel,
  decisionPayload,
  groupReviewChanges,
  humanizeRuleId,
  isRecordableDecision,
  newestPublishedRevision,
  pathGroupForPointer,
  readablePointer,
  reviewErrorMessage,
  reviewProgressText,
  reviewSpecSideFromQuery,
  reviewStatusBadge,
  reviewTabFromQuery,
  sameId,
  validateDecisionNote,
  type ReviewDetail,
  type ReviewerDecisionRow,
  type ReviewRecord,
} from '../lib/review-page';

const VIEWER = '11111111-1111-4111-8111-111111111111';
const OTHER = '22222222-2222-4222-8222-222222222222';

/**
 * A review record.
 *
 * @param overrides - Fields to change.
 * @returns The record.
 */
function record(overrides: Partial<ReviewRecord> = {}): ReviewRecord {
  return {
    id: 'review-1',
    tenant_id: 't-1',
    project_id: 'p-1',
    version_id: 'v-2',
    version_label: '2.0.0',
    requested_by: OTHER,
    requested_by_name: 'Rae Requester',
    state: 'in_review',
    round: 1,
    spec_fingerprint: 'sha256:a',
    reviewer_count: 2,
    approved_count: 0,
    changes_requested_count: 0,
    pending_count: 2,
    closed_at: null,
    closed_by: null,
    created_at: '2026-09-14T10:00:00Z',
    updated_at: '2026-09-14T10:00:00Z',
    ...overrides,
  };
}

/**
 * A reviewer row.
 *
 * @param overrides - Fields to change.
 * @returns The row.
 */
function reviewer(overrides: Partial<ReviewerDecisionRow> = {}): ReviewerDecisionRow {
  return {
    id: 'row-1',
    review_id: 'review-1',
    round: 1,
    user_id: VIEWER,
    user_name: 'Ravi Reviewer',
    decision: 'pending',
    note: null,
    decided_at: null,
    created_at: '2026-09-14T10:00:00Z',
    ...overrides,
  };
}

/**
 * A review detail.
 *
 * @param overrides - Fields to change.
 * @returns The detail.
 */
function detail(overrides: Partial<ReviewDetail> = {}): ReviewDetail {
  return { review: record(), reviewers: [reviewer()], history: [], spec_changed: false, ...overrides };
}

describe('tabs', () => {
  it('lists Changes, Spec and Discussion in that order', () => {
    expect(REVIEW_TABS).toEqual(['changes', 'spec', 'discussion']);
  });

  it('opens the asked-for tab and Changes for anything else', () => {
    expect(reviewTabFromQuery('spec')).toBe('spec');
    expect(reviewTabFromQuery(['discussion', 'spec'])).toBe('discussion');
    expect(reviewTabFromQuery('history')).toBe('changes');
    expect(reviewTabFromQuery(undefined)).toBe('changes');
    expect(reviewTabFromQuery(null)).toBe('changes');
  });
});

describe('the header', () => {
  it('badges each state, and a withdrawn review as withdrawn whatever its state', () => {
    expect(reviewStatusBadge(record())).toEqual({ label: 'In review', variant: 'warning' });
    expect(reviewStatusBadge(record({ state: 'approved' }))).toEqual({ label: 'Approved', variant: 'success' });
    expect(reviewStatusBadge(record({ state: 'changes_requested' }))).toEqual({
      label: 'Changes requested',
      variant: 'error',
    });
    expect(reviewStatusBadge(record({ state: 'approved', closed_at: '2026-09-15T00:00:00Z' }))).toEqual({
      label: 'Withdrawn',
      variant: 'secondary',
    });
  });

  it('badges each decision', () => {
    expect(DECISION_LABELS).toEqual({ approve: 'Approved', request_changes: 'Requested changes', pending: 'Pending' });
    expect(decisionBadgeVariant('approve')).toBe('success');
    expect(decisionBadgeVariant('request_changes')).toBe('error');
    expect(decisionBadgeVariant('pending')).toBe('secondary');
  });

  it('spells the tally, leaving out the parts that are zero', () => {
    expect(reviewProgressText(record())).toBe('0 of 2 approved · 2 pending');
    expect(reviewProgressText(record({ approved_count: 1, changes_requested_count: 1, pending_count: 0 }))).toBe(
      '1 of 2 approved · 1 requested changes'
    );
    expect(reviewProgressText(record({ approved_count: 2, pending_count: 0 }))).toBe('2 of 2 approved');
  });
});

describe('decisionBarModel', () => {
  it('offers the form to a pending reviewer of an open round whose spec still matches', () => {
    const model = decisionBarModel(detail(), VIEWER);
    expect(model.mode).toBe('decide');
    expect(model.mine?.id).toBe('row-1');
  });

  it('matches the viewer case-insensitively, as apiome-rest compares canonical ids', () => {
    expect(decisionBarModel(detail(), VIEWER.toUpperCase()).mode).toBe('decide');
  });

  it('tells a withdrawn review before anything else', () => {
    const model = decisionBarModel(detail({ review: record({ closed_at: '2026-09-15T00:00:00Z' }) }), VIEWER);
    expect(model.mode).toBe('withdrawn');
    expect(model.message).toBe('This review was withdrawn. Its decisions stay on record.');
  });

  it('tells someone who is not a reviewer of this round, including a former-round reviewer', () => {
    expect(decisionBarModel(detail(), OTHER).mode).toBe('not-reviewer');
    expect(decisionBarModel(detail(), null).mode).toBe('not-reviewer');
    const earlier = detail({ reviewers: [reviewer({ user_id: OTHER })], history: [reviewer({ id: 'old', round: 1 })] });
    expect(decisionBarModel(earlier, VIEWER).mode).toBe('not-reviewer');
  });

  it('tells a reviewer what they already decided', () => {
    const approved = decisionBarModel(
      detail({ reviewers: [reviewer({ decision: 'approve', decided_at: '2026-09-14T11:00:00Z' })] }),
      VIEWER
    );
    expect(approved).toMatchObject({ mode: 'decided', message: 'You approved this round.' });
    const changes = decisionBarModel(
      detail({ reviewers: [reviewer({ decision: 'request_changes', note: 'Rename it', decided_at: 'x' })] }),
      VIEWER
    );
    expect(changes).toMatchObject({ mode: 'decided', message: 'You requested changes in this round.' });
  });

  it('closes the form for a pending reviewer once someone requested changes', () => {
    const model = decisionBarModel(detail({ review: record({ state: 'changes_requested' }) }), VIEWER);
    expect(model.mode).toBe('round-decided');
  });

  it('closes the form while the spec no longer matches the round, but not when unknown', () => {
    expect(decisionBarModel(detail({ spec_changed: true }), VIEWER).mode).toBe('stale');
    expect(decisionBarModel(detail({ spec_changed: null }), VIEWER).mode).toBe('decide');
  });
});

describe('decisions', () => {
  it('requires a note to request changes, never to approve', () => {
    expect(validateDecisionNote('approve', '')).toBeNull();
    expect(validateDecisionNote('approve', undefined)).toBeNull();
    expect(validateDecisionNote('request_changes', '')).toBe('Say what needs to change before requesting changes.');
    expect(validateDecisionNote('request_changes', '   \n ')).toBe('Say what needs to change before requesting changes.');
    expect(validateDecisionNote('request_changes', 'Rename id')).toBeNull();
  });

  it('bounds the note at apiome-rest length', () => {
    expect(REVIEW_NOTE_MAX_LENGTH).toBe(5000);
    expect(validateDecisionNote('approve', 'x'.repeat(5000))).toBeNull();
    expect(validateDecisionNote('approve', 'x'.repeat(5001))).toBe('Keep the note to 5,000 characters.');
  });

  it('sends the note only when it says something', () => {
    expect(decisionPayload('approve', '')).toEqual({ decision: 'approve' });
    expect(decisionPayload('approve', '  ')).toEqual({ decision: 'approve' });
    expect(decisionPayload('request_changes', '  Rename id')).toEqual({ decision: 'request_changes', note: '  Rename id' });
  });

  it('accepts only the two recordable decisions', () => {
    expect(isRecordableDecision('approve')).toBe(true);
    expect(isRecordableDecision('request_changes')).toBe(true);
    expect(isRecordableDecision('pending')).toBe(false);
    expect(isRecordableDecision(undefined)).toBe(false);
  });

  it('explains every refusal code the decision endpoint can answer with', () => {
    for (const code of [
      'review-not-found',
      'review-not-reviewer',
      'review-already-decided',
      'review-not-in-review',
      'review-closed',
      'review-spec-changed',
      'review-version-published',
      'review-conflict',
    ]) {
      expect(REVIEW_ERROR_MESSAGES[code]).toBeTruthy();
    }
    expect(reviewErrorMessage('review-closed', 'fallback')).toBe('This review was withdrawn.');
    expect(reviewErrorMessage('something-new', 'fallback')).toBe('fallback');
    expect(reviewErrorMessage(null, 'fallback')).toBe('fallback');
  });
});

describe('classified changes', () => {
  it.each([
    ['', '/'],
    ['/', '/'],
    ['/paths/~1pets/get/responses/200', '/paths/~1pets'],
    ['paths/~1pets', '/paths/~1pets'],
    ['/components/schemas/Pet/properties/name', '/components/schemas/Pet'],
    ['/components/schemas', '/components/schemas'],
    ['/servers/0/url', '/servers'],
    ['/tags/1', '/tags'],
    ['/security/0', '/security'],
    ['/webhooks/newPet/post', '/webhooks'],
    ['/info/title', '/info'],
    ['/x-extension/a/b', '/x-extension/a'],
    ['/openapi', '/openapi'],
  ])('groups %s under %s, as apiome-rest does', (pointer, group) => {
    expect(pathGroupForPointer(pointer)).toBe(group);
  });

  it('spells pointers readably', () => {
    expect(readablePointer('/paths/~1pets~1{id}/get')).toBe('paths › /pets/{id} › get');
    expect(readablePointer('/')).toBe('Document');
  });

  it('turns rule ids into sentence-case words', () => {
    expect(humanizeRuleId('response-property-removed')).toBe('Response property removed');
    expect(humanizeRuleId('schema.type_changed')).toBe('Schema type changed');
    expect(humanizeRuleId('')).toBe('');
    expect(humanizeRuleId(undefined)).toBe('');
  });

  it("summarises with the generator's fallbacks", () => {
    expect(classifiedChangeSummary({ ruleId: 'operation-removed' })).toBe('Operation removed');
    expect(classifiedChangeSummary({ ruleId: 'x', unclassified: true })).toBe('Unclassified change (treated as breaking)');
    expect(classifiedChangeSummary({ ruleId: '', changeKind: 'removed' })).toBe('Change of kind removed');
    expect(classifiedChangeSummary({ ruleId: '' })).toBe('Change');
  });

  it('shapes live changes as changelog entries, coercing unknown severities', () => {
    const entries = classifiedChangesToEntries(
      [
        { ruleId: 'operation-removed', severity: 'breaking', pointer: '/paths/~1pets/get', changeKind: 'removed' },
        { ruleId: 'mystery', severity: 'weird', pointer: '/info/x', unclassified: true },
        { ruleId: 'mystery', severity: 'weird', pointer: '/info/y' },
      ],
      '1.0.0',
      '2.0.0'
    );
    expect(entries.map((entry) => [entry.severity, entry.pathGroup, entry.summary])).toEqual([
      ['breaking', '/paths/~1pets', 'Operation removed'],
      ['breaking', '/info', 'Unclassified change (treated as breaking)'],
      ['docs-only', '/info', 'Mystery'],
    ]);
    expect(entries[0]).toMatchObject({ fromVersion: '1.0.0', toVersion: '2.0.0', changeKind: 'removed' });
  });

  it('groups breaking first, then by path group in arrival order', () => {
    const sections = groupReviewChanges({
      head: { id: 'h', label: '2.0.0' },
      baseline: { id: 'b', label: '1.0.0' },
      changes: [
        { ruleId: 'description-changed', severity: 'docs-only', pointer: '/info/description' },
        { ruleId: 'property-added', severity: 'non-breaking', pointer: '/components/schemas/Pet/properties/tag' },
        { ruleId: 'operation-removed', severity: 'breaking', pointer: '/paths/~1pets/delete' },
        { ruleId: 'response-removed', severity: 'breaking', pointer: '/paths/~1pets/get/responses/404' },
        { ruleId: 'schema-removed', severity: 'breaking', pointer: '/components/schemas/Owner' },
      ],
    });
    expect(sections.map((section) => section.severity)).toEqual(['breaking', 'non-breaking', 'docs-only']);
    expect(sections[0].groups.map((group) => [group.pathGroup, group.entries.length])).toEqual([
      ['/paths/~1pets', 2],
      ['/components/schemas/Owner', 1],
    ]);
  });

  it('counts changes in words', () => {
    expect(changeCountText(1)).toBe('1 change');
    expect(changeCountText(0)).toBe('0 changes');
    expect(changeCountText(3)).toBe('3 changes');
  });
});

describe('the baseline', () => {
  const rows = [
    { id: 'draft', version_id: '3.0.0', published: false, created_at: '2026-09-01T00:00:00Z' },
    { id: 'old', version_id: '1.0.0', published: true, published_at: '2026-01-01T00:00:00Z' },
    { id: 'new', version_id: '2.0.0', published: true, published_at: '2026-06-01T00:00:00Z' },
    { id: 'undated', version_id: '0.9.0', published: true, published_at: null, created_at: '2025-01-01T00:00:00Z' },
  ];

  it('is the newest published revision by publication time', () => {
    expect(newestPublishedRevision(rows)?.id).toBe('new');
  });

  it('never chooses the excluded revision', () => {
    expect(newestPublishedRevision(rows, 'NEW'.toLowerCase())?.id).toBe('old');
  });

  it('falls back to creation time and answers null when nothing is published', () => {
    expect(newestPublishedRevision([rows[3]])?.id).toBe('undated');
    expect(newestPublishedRevision([rows[0]])).toBeNull();
    expect(newestPublishedRevision([{ id: 'x', version_id: '1', published: true }])).toBeNull();
  });

  it('reads the spec side, defaulting to the version under review', () => {
    expect(reviewSpecSideFromQuery('base')).toBe('base');
    expect(reviewSpecSideFromQuery('head')).toBe('head');
    expect(reviewSpecSideFromQuery('BASE')).toBe('head');
    expect(reviewSpecSideFromQuery(null)).toBe('head');
  });

  it('compares ids case-insensitively and never matches a missing one', () => {
    expect(sameId(VIEWER, VIEWER.toUpperCase())).toBe(true);
    expect(sameId(null, null)).toBe(false);
    expect(sameId(VIEWER, OTHER)).toBe(false);
  });
});
