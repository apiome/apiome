/**
 * The merge request page, rendered (COL-4.3, #4527).
 *
 * Mounts the real `MergeRequestPageClient` against mocked BFF routes and pins the acceptance
 * criteria in a DOM:
 *
 *   1. **Reviewers decide through the review flow** — the Review tab shows the branch tip's review
 *      and links to the review page; Merge stays disabled until readiness allows it.
 *   2. **Merge executes via a merge session** — pressing Merge posts to `…/merge` and the page shows
 *      the merged state.
 *   3. **The Changes tab shows the classified diff** from the merge base to the branch tip.
 *   4. **Conflicts surface through the existing conflict UX** — a refused merge with `mr-conflicts`
 *      reloads the request and opens the Conflicts tab, listing the session's paths.
 */

import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';

import type { MergeRequestDetail } from '../lib/merge-requests';
import type { ReviewDetail } from '../lib/review-page';

jest.mock('sonner', () => ({
  toast: { success: jest.fn(), error: jest.fn() },
}));

jest.mock('@/app/components/ui/code/JsonDiffViewer', () => ({
  JsonDiffViewer: () =>
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    require('react').createElement('div', { 'data-testid': 'json-diff-viewer' }),
}));

import MergeRequestPageClient from '../src/app/components/ade/merge-requests/MergeRequestPageClient';
import { writeA11yFixture } from './helpers/a11y-fixture-dump';

const MR_ID = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd';
const BASE = `/api/merge-requests/${MR_ID}`;
const VIEWER = '11111111-1111-4111-8111-111111111111';
const REX = '22222222-2222-4222-8222-222222222222';

const review = (state: 'in_review' | 'approved' = 'in_review'): ReviewDetail =>
  ({
    review: {
      id: 'r-1',
      tenant_id: 't-1',
      project_id: 'p-1',
      version_id: 'v-tip',
      version_label: '1.0.1',
      requested_by: VIEWER,
      requested_by_name: 'Rita',
      state,
      round: 1,
      spec_fingerprint: 'sha256:x',
      reviewer_count: 1,
      approved_count: state === 'approved' ? 1 : 0,
      changes_requested_count: 0,
      pending_count: state === 'approved' ? 0 : 1,
      closed_at: null,
      closed_by: null,
      created_at: '2026-11-14T00:00:00Z',
      updated_at: '2026-11-14T00:00:00Z',
    },
    reviewers: [
      {
        id: 'rr-1',
        review_id: 'r-1',
        round: 1,
        user_id: REX,
        user_name: 'Rex',
        decision: state === 'approved' ? 'approve' : 'pending',
        note: null,
        decided_at: null,
        created_at: '2026-11-14T00:00:00Z',
      },
    ],
    history: [],
    spec_changed: false,
  }) as unknown as ReviewDetail;

const detail = (over: Partial<MergeRequestDetail> = {}, recordOver: Partial<MergeRequestDetail['merge_request']> = {}): MergeRequestDetail => ({
  merge_request: {
    id: MR_ID,
    tenant_id: 't-1',
    project_id: 'p-1',
    title: 'Add tags to Pet',
    description: 'Pets can be tagged.',
    state: 'open',
    source_branch_id: 'b-src',
    source_branch_name: 'feature/tags',
    target_branch_id: 'b-main',
    target_branch_name: 'main',
    review_id: 'r-1',
    merge_session_id: null,
    merged_version_id: null,
    created_by: VIEWER,
    created_by_name: 'Rita',
    created_at: '2026-11-14T00:00:00Z',
    updated_at: '2026-11-14T00:00:00Z',
    merged_by: null,
    merged_at: null,
    closed_by: null,
    closed_at: null,
    ...recordOver,
  },
  source_tip_revision_id: 'v-tip',
  source_tip_version_label: '1.0.1',
  target_tip_revision_id: 'v-line',
  target_tip_version_label: '1.0.0',
  merge_base_revision_id: 'v-line',
  merge_base_version_label: '1.0.0',
  review: review(),
  review_outdated: false,
  merge_session: null,
  conflicts: [],
  readiness: {
    can_merge: false,
    blockers: [{ code: 'review-pending', message: '1 reviewer(s) have not decided yet.' }],
    approval: null,
  },
  ...over,
});

const ready = (): MergeRequestDetail =>
  detail({ review: review('approved'), readiness: { can_merge: true, blockers: [], approval: null } });

const CHANGES = {
  success: true,
  head: { id: 'v-tip', label: '1.0.1' },
  baseline: { id: 'v-line', label: '1.0.0' },
  initialPublication: false,
  changes: [{ ruleId: 'property-added', severity: 'non-breaking', pointer: '/components/schemas/Pet/properties/tags' }],
  counts: { 'non-breaking': 1, total: 1 },
  maxSeverity: 'non-breaking',
  classifiedError: null,
};

type Handler = (url: string, body: unknown) => unknown;

/**
 * Mock the BFF: GETs answer from `pages`, POSTs from `onPost`.
 *
 * @param current - The merge request the page reads (a getter, so a test can change it).
 * @param onPost - The answer to an action.
 * @returns The fetch mock.
 */
function mockBff(current: () => MergeRequestDetail, onPost: Handler = () => ({ success: true, mergeRequest: current() })) {
  const fetchMock = jest.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === 'POST') {
      return { json: async () => onPost(url, JSON.parse(String(init.body ?? '{}'))) } as Response;
    }
    if (url === `${BASE}/changes`) return { json: async () => CHANGES } as Response;
    return {
      json: async () => ({
        success: true,
        mergeRequest: current(),
        project: { id: 'p-1', name: 'Pets', slug: 'pets' },
        viewerId: VIEWER,
      }),
    } as Response;
  });
  global.fetch = fetchMock as unknown as typeof fetch;
  return fetchMock;
}

afterEach(() => jest.restoreAllMocks());

it('shows the header, the blockers, and keeps Merge disabled while the review is pending', async () => {
  mockBff(() => detail());
  render(<MergeRequestPageClient mergeRequestId={MR_ID} />);
  expect(await screen.findByRole('heading', { name: /^Add tags to Pet/ })).toBeInTheDocument();
  expect(screen.getByTestId('mr-state')).toHaveTextContent('Open');
  expect(screen.getByTestId('mr-branches')).toHaveTextContent('feature/tags');
  expect(screen.getByTestId('mr-branches')).toHaveTextContent('main');
  expect(screen.getByTestId('mr-description')).toHaveTextContent('Pets can be tagged.');
  expect(screen.getByTestId('mr-blocker-review-pending')).toBeInTheDocument();
  expect(screen.getByTestId('mr-merge')).toBeDisabled();
});

it('shows the classified diff from the merge base on the Changes tab', async () => {
  mockBff(() => detail());
  render(<MergeRequestPageClient mergeRequestId={MR_ID} />);
  expect(await screen.findByTestId('review-changes-compare')).toHaveTextContent(
    'Compared with v1.0.0, the merge base · 1 non-breaking'
  );
  expect(screen.getAllByTestId('review-change')).toHaveLength(1);
});

it('shows the branch tip review and links to the review page', async () => {
  mockBff(() => detail());
  render(<MergeRequestPageClient mergeRequestId={MR_ID} initialTab="review" />);
  expect(await screen.findByTestId('mr-review-status')).toHaveTextContent('In review');
  expect(screen.getByTestId('mr-review-link')).toHaveAttribute('href', '/ade/reviews/r-1');
  expect(screen.getByText('Rex')).toBeInTheDocument();
});

it('merges through the merge route once ready and shows the merged state', async () => {
  let current = ready();
  const fetchMock = mockBff(
    () => current,
    (url) => {
      current = detail(
        { readiness: { can_merge: false, blockers: [], approval: null } },
        { state: 'merged', merged_at: '2026-11-14T01:00:00Z', merged_version_id: 'v-merged' }
      );
      return url.endsWith('/merge') ? { success: true, mergeRequest: current } : { success: false };
    }
  );
  render(<MergeRequestPageClient mergeRequestId={MR_ID} />);
  const merge = await screen.findByTestId('mr-merge');
  expect(merge).toBeEnabled();
  fireEvent.click(merge);
  await waitFor(() =>
    expect(fetchMock).toHaveBeenCalledWith(`${BASE}/merge`, expect.objectContaining({ method: 'POST' }))
  );
  expect(await screen.findByTestId('mr-summary')).toHaveTextContent('Merged into main.');
  expect(screen.getByTestId('mr-state')).toHaveTextContent('Merged');
  expect(screen.queryByTestId('mr-merge')).toBeNull();
});

it('opens the Conflicts tab with the session paths when the merge finds conflicts', async () => {
  let current = ready();
  mockBff(
    () => current,
    () => {
      current = detail({
        review: review('approved'),
        merge_session: {
          id: 'ms-1',
          status: 'resolving',
          sourceBranchName: 'feature/tags',
          targetBranchName: 'main',
          mergeBaseVersionId: 'v-line',
          sourceTipVersionId: 'v-tip',
          targetTipVersionId: 'v-line',
        },
        conflicts: [{ path: 'components.schemas.Pet', kinds: ['threeWay'] }],
        readiness: {
          can_merge: false,
          blockers: [{ code: 'conflicts', message: '1 conflicting path(s) with main.' }],
          approval: null,
        },
      });
      return { success: false, code: 'mr-conflicts', error: 'conflicts' };
    }
  );
  render(<MergeRequestPageClient mergeRequestId={MR_ID} />);
  fireEvent.click(await screen.findByTestId('mr-merge'));
  expect(await screen.findByTestId('mr-action-error')).toHaveTextContent(/conflicts with the line/);
  const pane = await screen.findByTestId('mr-conflicts');
  expect(within(pane).getByText('components.schemas.Pet')).toBeInTheDocument();
  expect(screen.getByTestId('mr-tab-conflicts')).toHaveAttribute('aria-selected', 'true');
  expect(screen.getByTestId('mr-tab-conflicts-count')).toHaveTextContent('1');
});

it('offers a review of the current tip when the branch moved on', async () => {
  const fetchMock = mockBff(() =>
    detail({
      review_outdated: true,
      readiness: {
        can_merge: false,
        blockers: [{ code: 'review-outdated', message: 'The branch moved on.' }],
        approval: null,
      },
    })
  );
  render(<MergeRequestPageClient mergeRequestId={MR_ID} />);
  fireEvent.click(await screen.findByTestId('mr-review-tip'));
  await waitFor(() =>
    expect(fetchMock).toHaveBeenCalledWith(`${BASE}/review`, expect.objectContaining({ method: 'POST' }))
  );
});

it('lets the immutability override enable Merge only with a reason', async () => {
  const fetchMock = mockBff(() =>
    detail({
      review: review('approved'),
      readiness: {
        can_merge: false,
        blockers: [{ code: 'target-immutable', message: 'The tip of main is published and immutable.' }],
        approval: null,
      },
    })
  );
  render(<MergeRequestPageClient mergeRequestId={MR_ID} />);
  const merge = await screen.findByTestId('mr-merge');
  expect(merge).toBeDisabled();
  fireEvent.click(screen.getByTestId('mr-override-toggle'));
  expect(merge).toBeDisabled();
  fireEvent.change(screen.getByTestId('mr-override-reason'), { target: { value: 'Hotfix for an outage' } });
  expect(merge).toBeEnabled();
  fireEvent.click(merge);
  await waitFor(() => {
    const call = fetchMock.mock.calls.find(([url]) => url === `${BASE}/merge`);
    expect(JSON.parse(String(call?.[1]?.body))).toEqual({
      override_published_immutability: true,
      override_reason: 'Hotfix for an outage',
    });
  });
});

it('shows a load failure with a retry', async () => {
  global.fetch = jest.fn(async () => ({
    json: async () => ({ success: false, code: 'mr-not-found', error: 'nope' }),
  })) as unknown as typeof fetch;
  render(<MergeRequestPageClient mergeRequestId={MR_ID} />);
  expect(await screen.findByTestId('mr-error')).toHaveTextContent('This merge request no longer exists.');
});

describe('fixture', () => {
  /** The page root — `.page` when the shell's chrome rendered one. */
  const page = () => (document.querySelector('.page') ?? document.body.firstElementChild) as HTMLElement;

  const PAYMENTS = {
    title: 'Add refund reason codes',
    description: 'Refunds carry a reason code so finance can report on them.',
    source_branch_name: 'feature/refund-reasons',
    created_by_name: 'Priya Raman',
  };

  const REFUND_CHANGES = {
    ...CHANGES,
    head: { id: 'v-tip', label: '2.4.1' },
    baseline: { id: 'v-line', label: '2.4.0' },
    changes: [
      { ruleId: 'property-added', severity: 'non-breaking', pointer: '/components/schemas/Refund/properties/reason_code' },
      { ruleId: 'enum-value-added', severity: 'non-breaking', pointer: '/components/schemas/RefundReason/enum' },
      { ruleId: 'description-changed', severity: 'docs-only', pointer: '/components/schemas/Refund' },
    ],
    counts: { 'non-breaking': 2, 'docs-only': 1, total: 3 },
  };

  /**
   * A Payments API merge request.
   *
   * @param over - Detail fields to change.
   * @returns The detail.
   */
  const payments = (over: Partial<MergeRequestDetail> = {}): MergeRequestDetail =>
    detail(
      {
        source_tip_version_label: '2.4.1',
        target_tip_version_label: '2.4.0',
        merge_base_version_label: '2.4.0',
        review: review('approved'),
        readiness: { can_merge: true, blockers: [], approval: null },
        ...over,
      },
      PAYMENTS
    );

  /**
   * Mock the BFF with the Payments data.
   *
   * @param current - The merge request.
   */
  const install = (current: MergeRequestDetail) => {
    global.fetch = jest.fn(async (url: string) => ({
      json: async () =>
        url.endsWith('/changes')
          ? REFUND_CHANGES
          : {
              success: true,
              mergeRequest: current,
              project: { id: 'p-1', name: 'Payments API', slug: 'payments-api' },
              viewerId: VIEWER,
            },
    })) as unknown as typeof fetch;
  };

  it('renders a merge request ready to merge', async () => {
    install(payments());
    render(<MergeRequestPageClient mergeRequestId={MR_ID} />);
    await screen.findByRole('heading', { name: /^Add refund reason codes/ });
    await screen.findByTestId('review-classified');
    expect(screen.getByTestId('mr-merge')).toBeEnabled();
    writeA11yFixture('merge-request', page().outerHTML);
  });

  it('renders the conflicts a merge session found', async () => {
    install(
      payments({
        merge_session: {
          id: 'ms-1',
          status: 'resolving',
          sourceBranchName: 'feature/refund-reasons',
          targetBranchName: 'main',
          mergeBaseVersionId: 'v-line',
          sourceTipVersionId: 'v-tip',
          targetTipVersionId: 'v-main',
        },
        conflicts: [
          { path: 'components.schemas.Refund', kinds: ['threeWay'] },
          { path: 'components.schemas.RefundReason', kinds: ['threeWay', 'twoWay'] },
        ],
        readiness: {
          can_merge: false,
          blockers: [{ code: 'conflicts', message: '2 conflicting path(s) with main. Update the branch, then check again.' }],
          approval: null,
        },
      })
    );
    render(<MergeRequestPageClient mergeRequestId={MR_ID} initialTab="conflicts" />);
    await screen.findByTestId('mr-conflicts');
    expect(screen.getByTestId('mr-merge')).toBeDisabled();
    writeA11yFixture('merge-request-conflicts', page().outerHTML);
  });
});
