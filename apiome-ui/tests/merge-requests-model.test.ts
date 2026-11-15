/**
 * The merge request UI model (COL-4.3, #4527): labels, the page's tabs, form validation, request
 * payloads and refusal messages.
 */

import {
  MERGE_REQUEST_STATE_BADGE,
  defaultTargetBranch,
  draftBranchFormError,
  draftBranchPayload,
  mergeRequestErrorMessage,
  mergeRequestHref,
  mergeRequestTabFromQuery,
  openMergeRequestFormError,
  openMergeRequestPayload,
  readinessSummary,
  type DraftBranchRecord,
  type MergeRequestDetail,
  type OpenMergeRequestForm,
} from '../lib/merge-requests';

const record = (over: Partial<MergeRequestDetail['merge_request']> = {}): MergeRequestDetail['merge_request'] => ({
  id: 'mr-1',
  tenant_id: 't-1',
  project_id: 'p-1',
  title: 'Add tags',
  description: null,
  state: 'open',
  source_branch_id: 'b-src',
  source_branch_name: 'feature/tags',
  target_branch_id: 'b-main',
  target_branch_name: 'main',
  review_id: 'r-1',
  merge_session_id: null,
  merged_version_id: null,
  created_by: 'u-1',
  created_by_name: 'Rita',
  created_at: '',
  updated_at: '',
  merged_by: null,
  merged_at: null,
  closed_by: null,
  closed_at: null,
  ...over,
});

const draft = (name: string, base: string | null): DraftBranchRecord => ({
  id: `id-${name}`,
  project_id: 'p-1',
  name,
  tip_revision_id: 'v-2',
  tip_version_label: '1.0.1',
  base_branch_id: base ? `id-${base}` : null,
  base_branch_name: base,
  branched_from_revision_id: 'v-1',
  created_by: null,
  created_at: null,
});

describe('readinessSummary', () => {
  it('says what is left, or the outcome', () => {
    const blockers = [{ code: 'review-pending', message: '1 reviewer(s) have not decided yet.' }];
    expect(readinessSummary({ merge_request: record(), readiness: { can_merge: true, blockers: [], approval: null } })).toBe(
      'Ready to merge into main.'
    );
    expect(readinessSummary({ merge_request: record(), readiness: { can_merge: false, blockers, approval: null } })).toBe(
      '1 thing to do before this can merge.'
    );
    expect(
      readinessSummary({
        merge_request: record(),
        readiness: { can_merge: false, blockers: [...blockers, ...blockers], approval: null },
      })
    ).toBe('2 things to do before this can merge.');
    expect(
      readinessSummary({ merge_request: record({ state: 'merged' }), readiness: { can_merge: false, blockers: [], approval: null } })
    ).toBe('Merged into main.');
    expect(
      readinessSummary({ merge_request: record({ state: 'closed' }), readiness: { can_merge: false, blockers: [], approval: null } })
    ).toBe('Closed without merging.');
  });
});

describe('labels and links', () => {
  it('names every state and links the page', () => {
    expect(MERGE_REQUEST_STATE_BADGE.open.label).toBe('Open');
    expect(MERGE_REQUEST_STATE_BADGE.merged.variant).toBe('success');
    expect(mergeRequestHref('a b')).toBe('/ade/merge-requests/a%20b');
  });

  it('reads the tab from the query, defaulting to Changes', () => {
    expect(mergeRequestTabFromQuery('conflicts')).toBe('conflicts');
    expect(mergeRequestTabFromQuery(['review'])).toBe('review');
    expect(mergeRequestTabFromQuery('bogus')).toBe('changes');
    expect(mergeRequestTabFromQuery(undefined)).toBe('changes');
  });
});

describe('the New draft branch form', () => {
  const form = { name: 'feature/tags', baseBranch: 'main', versionLabel: '' };

  it('accepts a valid form and refuses each mistake', () => {
    expect(draftBranchFormError(form, ['main'])).toBeNull();
    expect(draftBranchFormError({ ...form, name: ' ' }, [])).toBe('Name the branch.');
    expect(draftBranchFormError({ ...form, name: '1bad' }, [])).toMatch(/start with a letter/);
    expect(draftBranchFormError(form, ['feature/tags'])).toBe('A branch named feature/tags already exists.');
    expect(draftBranchFormError({ ...form, baseBranch: '' }, [])).toBe('Choose the version line to draft off.');
    expect(draftBranchFormError({ ...form, versionLabel: '1.4' }, [])).toBe('The version label must look like 1.4.1.');
    expect(draftBranchFormError({ ...form, versionLabel: '1.4.1' }, [])).toBeNull();
  });

  it('sends the label only when one is typed', () => {
    expect(draftBranchPayload({ ...form, name: ' feature/tags ' })).toEqual({ name: 'feature/tags', base_branch: 'main' });
    expect(draftBranchPayload({ ...form, versionLabel: ' 2.0.0 ' })).toEqual({
      name: 'feature/tags',
      base_branch: 'main',
      version_label: '2.0.0',
    });
  });
});

describe('the Open merge request form', () => {
  const form: OpenMergeRequestForm = {
    sourceBranch: 'feature/tags',
    targetBranch: 'main',
    title: 'Add tags',
    description: '',
    reviewers: ['u-2'],
  };

  it('accepts a valid form and refuses each mistake', () => {
    expect(openMergeRequestFormError(form)).toBeNull();
    expect(openMergeRequestFormError({ ...form, sourceBranch: '' })).toBe('Choose the draft branch to merge.');
    expect(openMergeRequestFormError({ ...form, targetBranch: '' })).toBe('Choose the version line to merge into.');
    expect(openMergeRequestFormError({ ...form, targetBranch: 'feature/tags' })).toBe(
      'A branch cannot be merged into itself.'
    );
    expect(openMergeRequestFormError({ ...form, title: '  ' })).toBe('Give the merge request a title.');
    expect(openMergeRequestFormError({ ...form, title: 'x'.repeat(201) })).toMatch(/under 200/);
    expect(openMergeRequestFormError({ ...form, reviewers: [] })).toBe('Ask at least one reviewer.');
  });

  it('trims, drops an empty description and de-duplicates reviewers', () => {
    expect(openMergeRequestPayload({ ...form, title: ' Add tags ', reviewers: ['u-2', 'u-2', 'u-3'] })).toEqual({
      source_branch: 'feature/tags',
      target_branch: 'main',
      title: 'Add tags',
      reviewers: ['u-2', 'u-3'],
    });
    expect(openMergeRequestPayload({ ...form, description: ' why ' }).description).toBe('why');
  });

  it('defaults the target to the line the draft was drafted off', () => {
    const drafts = [draft('feature/tags', 'main'), draft('fix/old', null)];
    expect(defaultTargetBranch(drafts, 'feature/tags')).toBe('main');
    expect(defaultTargetBranch(drafts, 'fix/old')).toBe('');
    expect(defaultTargetBranch(drafts, 'missing')).toBe('');
  });
});

describe('mergeRequestErrorMessage', () => {
  it('says a known refusal plainly and falls back to the server message', () => {
    expect(mergeRequestErrorMessage('mr-conflicts', 'x')).toMatch(/conflicts with the line/);
    expect(mergeRequestErrorMessage('PUBLISHED_IMMUTABLE', 'x')).toMatch(/tenant administrator/);
    expect(mergeRequestErrorMessage('something-new', 'Server said no')).toBe('Server said no');
    expect(mergeRequestErrorMessage(undefined, 'Server said no')).toBe('Server said no');
  });
});
