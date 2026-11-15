/**
 * The Versions screen's Merge requests tab and its two dialogs (COL-4.3, #4527).
 *
 * Pinned: the list reads the chosen state; draft branches show the line they were drafted off and
 * offer a merge request only when none is open; **New draft branch** posts the branch off the chosen
 * line; **Open merge request** defaults the target to that line, asks the chosen reviewers, and
 * goes to the new merge request's page.
 */

import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';

import type { DraftBranchRecord, MergeRequestRecord } from '../lib/merge-requests';
import type { VersionBranchRow } from '../src/app/components/ade/version-dialogs/types';

const push = jest.fn();
jest.mock('next/navigation', () => ({ useRouter: () => ({ push }) }));

import { MergeRequestsPanel } from '../src/app/components/ade/merge-requests/MergeRequestsPanel';
import { Page, PageBody } from '../src/app/components/shell/pageChrome';
import { writeA11yFixture } from './helpers/a11y-fixture-dump';

const PROJECT = 'p-1';
const BRANCHES: VersionBranchRow[] = [
  { id: 'b-main', name: 'main', tip_version_id: 'v-1', tip_version_string: '1.0.0', is_default: true },
];

const draft = (name: string, id = `b-${name}`): DraftBranchRecord => ({
  id,
  project_id: PROJECT,
  name,
  tip_revision_id: 'v-2',
  tip_version_label: '1.0.1',
  base_branch_id: 'b-main',
  base_branch_name: 'main',
  branched_from_revision_id: 'v-1',
  created_by: null,
  created_at: null,
});

const request = (over: Partial<MergeRequestRecord> = {}): MergeRequestRecord => ({
  id: 'mr-1',
  tenant_id: 't-1',
  project_id: PROJECT,
  title: 'Add tags',
  description: null,
  state: 'open',
  source_branch_id: 'b-feature/tags',
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

/**
 * Mock the BFF routes the tab and its dialogs call.
 *
 * @param state - What the routes answer with.
 * @returns The fetch mock.
 */
function mockBff(state: { drafts: DraftBranchRecord[]; open: MergeRequestRecord[]; merged?: MergeRequestRecord[] }) {
  const fetchMock = jest.fn(async (url: string, init?: RequestInit) => {
    const reply = (body: unknown) => ({ json: async () => body }) as Response;
    if (init?.method === 'POST' && url.endsWith('/draft-branches')) {
      return reply({ success: true, branch: draft('feature/new') });
    }
    if (init?.method === 'POST' && url.endsWith('/merge-requests')) {
      return reply({ success: true, mergeRequest: { merge_request: request({ id: 'mr-new' }) } });
    }
    if (url.endsWith('/draft-branches')) return reply({ success: true, branches: state.drafts });
    if (url.includes('/merge-requests?state=merged')) return reply({ success: true, merge_requests: state.merged ?? [] });
    if (url.includes('/merge-requests?state=')) return reply({ success: true, merge_requests: state.open });
    if (url === '/api/merge-requests/reviewers') {
      return reply({ success: true, reviewers: [{ user_id: 'rex', name: 'Rex', email: 'rex@example.com' }] });
    }
    return reply({ success: false });
  });
  global.fetch = fetchMock as unknown as typeof fetch;
  return fetchMock;
}

afterEach(() => {
  jest.restoreAllMocks();
  push.mockReset();
});

it('lists open merge requests and switches state', async () => {
  const fetchMock = mockBff({
    drafts: [draft('feature/tags')],
    open: [request()],
    merged: [request({ id: 'mr-2', title: 'Old change', state: 'merged' })],
  });
  render(<MergeRequestsPanel projectId={PROJECT} branches={BRANCHES} />);
  const row = await screen.findByTestId('mr-row');
  expect(within(row).getByRole('link', { name: 'Add tags' })).toHaveAttribute('href', '/ade/merge-requests/mr-1');
  fireEvent.click(screen.getByTestId('mr-filter-merged'));
  expect(await screen.findByRole('link', { name: 'Old change' })).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledWith(`/api/projects/${PROJECT}/merge-requests?state=merged`, undefined);
});

it('shows each draft with its line, linking an open request or offering one', async () => {
  mockBff({ drafts: [draft('feature/tags'), draft('feature/free')], open: [request()] });
  render(<MergeRequestsPanel projectId={PROJECT} branches={BRANCHES} />);
  await waitFor(() => expect(screen.getAllByTestId('mr-draft-row')).toHaveLength(2));
  const [tagged, free] = screen.getAllByTestId('mr-draft-row');
  expect(tagged).toHaveTextContent('off main · tip v1.0.1');
  expect(within(tagged).getByRole('link', { name: 'Open merge request' })).toHaveAttribute(
    'href',
    '/ade/merge-requests/mr-1'
  );
  expect(within(free).getByTestId('mr-draft-open')).toBeInTheDocument();
});

it('creates a draft branch off the default line', async () => {
  const onBranchesChanged = jest.fn();
  const fetchMock = mockBff({ drafts: [], open: [] });
  render(<MergeRequestsPanel projectId={PROJECT} branches={BRANCHES} onBranchesChanged={onBranchesChanged} />);
  fireEvent.click(await screen.findByTestId('mr-new-draft'));
  fireEvent.change(await screen.findByTestId('draft-branch-name'), { target: { value: 'feature/new' } });
  fireEvent.click(screen.getByTestId('draft-branch-create'));
  await waitFor(() => expect(onBranchesChanged).toHaveBeenCalled());
  const call = fetchMock.mock.calls.find(([url, init]) => url.endsWith('/draft-branches') && init?.method === 'POST');
  expect(JSON.parse(String(call?.[1]?.body))).toEqual({ name: 'feature/new', base_branch: 'main' });
});

it('refuses a draft branch name that is taken, before sending anything', async () => {
  const fetchMock = mockBff({ drafts: [], open: [] });
  render(<MergeRequestsPanel projectId={PROJECT} branches={BRANCHES} />);
  fireEvent.click(await screen.findByTestId('mr-new-draft'));
  fireEvent.change(await screen.findByTestId('draft-branch-name'), { target: { value: 'main' } });
  fireEvent.click(screen.getByTestId('draft-branch-create'));
  expect(await screen.findByTestId('draft-branch-form-error')).toHaveTextContent('A branch named main already exists.');
  expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false);
});

it('opens a merge request for a draft into its line with the chosen reviewer', async () => {
  const fetchMock = mockBff({ drafts: [draft('feature/free')], open: [] });
  render(<MergeRequestsPanel projectId={PROJECT} branches={BRANCHES} />);
  fireEvent.click(await screen.findByTestId('mr-draft-open'));
  fireEvent.change(await screen.findByTestId('open-mr-title'), { target: { value: 'Free pets' } });
  const reviewer = await screen.findByTestId('open-mr-reviewer');
  fireEvent.click(within(reviewer).getByRole('checkbox'));
  fireEvent.click(screen.getByTestId('open-mr-submit'));
  await waitFor(() => expect(push).toHaveBeenCalledWith('/ade/merge-requests/mr-new'));
  const call = fetchMock.mock.calls.find(([url, init]) => url.endsWith('/merge-requests') && init?.method === 'POST');
  expect(JSON.parse(String(call?.[1]?.body))).toEqual({
    source_branch: 'feature/free',
    target_branch: 'main',
    title: 'Free pets',
    reviewers: ['rex'],
  });
});

it('fixture: renders the Merge requests tab of a project', async () => {
  mockBff({
    drafts: [draft('feature/refund-reasons'), draft('fix/currency-codes')],
    open: [
      request({
        title: 'Add refund reason codes',
        source_branch_id: 'b-feature/refund-reasons',
        source_branch_name: 'feature/refund-reasons',
        created_by_name: 'Priya Raman',
      }),
    ],
  });
  const { container } = render(
    <Page>
      <PageBody>
        <MergeRequestsPanel projectId={PROJECT} branches={BRANCHES} />
      </PageBody>
    </Page>
  );
  await screen.findByTestId('mr-row');
  await waitFor(() => expect(screen.getAllByTestId('mr-draft-row')).toHaveLength(2));
  writeA11yFixture('versions-merge-requests', (container.firstElementChild as HTMLElement).outerHTML);
});
