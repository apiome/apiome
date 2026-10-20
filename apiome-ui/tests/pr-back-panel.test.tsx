/**
 * The "Sync back to repositories" section of the Sources tab (REPO-5.8, #2793), rendered.
 *
 * Mounts the real `PrBackPanel` against a mocked BFF: eligible repositories offer Preview and
 * Open pull request, ineligible ones say why and offer neither, a preview sends `dryRun: true`
 * and shows the files and the description, opening shows the pull request link, and a refusal
 * is shown in apiome-rest's words.
 */

import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';

import { PrBackPanel } from '../src/app/components/ade/versions/PrBackPanel';

const PROJECT_ID = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const VERSION_ID = '11111111-1111-4111-8111-111111111111';
const REPO_OK = '66666666-6666-4666-8666-666666666666';
const REPO_OFF = '66666666-6666-4666-8666-666666666667';

const REPOSITORIES = {
  success: true,
  repositories: [
    {
      repositoryId: REPO_OK,
      repositoryFullName: 'acme/users',
      files: [{ path: 'openapi.yaml', branch: 'main', precedence: 1 }],
      eligible: true,
      baseBranch: 'main',
    },
    {
      repositoryId: REPO_OFF,
      repositoryFullName: 'acme/billing',
      files: [{ path: 'billing.json', branch: 'main', precedence: 2 }],
      eligible: false,
      reasonCode: 'pr-back-not-configured',
      reason: 'acme/billing has no PR-back settings, so no project may open pull requests into it.',
    },
  ],
};

function outcome(status: string, extra: Record<string, unknown> = {}) {
  return {
    success: true,
    status,
    dryRun: status === 'preview',
    versionLabel: '1.4.0',
    repositoryFullName: 'acme/users',
    baseBranch: 'main',
    branchName: 'apiome/pr-back-shop-main',
    title: 'Apiome: sync Shop 1.4.0',
    body: '## Shop 1.4.0 — rendered from Apiome',
    commitMessage: 'Sync Shop 1.4.0 from Apiome',
    files: [
      {
        path: 'openapi.yaml',
        status: 'modified',
        paths: 2,
        schemas: 1,
        counts: {},
        foreignRefs: ['Invoice'],
        notes: [],
      },
    ],
    skipped: [],
    ...extra,
  };
}

let syncReply: { status: number; body: unknown };
let listReply: { status: number; body: unknown };
let posted: unknown[];

beforeEach(() => {
  posted = [];
  listReply = { status: 200, body: REPOSITORIES };
  syncReply = { status: 200, body: outcome('preview') };
  global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const reply = url.endsWith('/pr-back/repositories') ? listReply : syncReply;
    if (init?.method === 'POST') posted.push(JSON.parse(String(init.body)));
    return { ok: reply.status < 400, status: reply.status, json: async () => reply.body } as unknown as Response;
  }) as unknown as typeof fetch;
});

function mount() {
  return render(<PrBackPanel projectId={PROJECT_ID} versionId={VERSION_ID} versionLabel="1.4.0" />);
}

test('lists repositories with their files and eligibility', async () => {
  mount();
  const rows = await screen.findAllByTestId('pr-back-repository');
  expect(rows).toHaveLength(2);
  expect(within(rows[0]).getByText('acme/users')).toBeInTheDocument();
  expect(within(rows[0]).getByTestId('pr-back-eligible')).toHaveTextContent('Can sync into main');
  expect(within(rows[0]).getByTestId('pr-back-open')).toBeEnabled();
  expect(within(rows[1]).getByTestId('pr-back-ineligible')).toHaveTextContent('Not allowed');
  expect(within(rows[1]).getByTestId('pr-back-reason')).toHaveTextContent(/no PR-back settings/);
  expect(within(rows[1]).getByTestId('pr-back-open')).toBeDisabled();
  expect(within(rows[1]).getByTestId('pr-back-preview')).toBeDisabled();
});

test('preview sends a dry run and shows the files and the description', async () => {
  mount();
  const [row] = await screen.findAllByTestId('pr-back-repository');
  fireEvent.click(within(row).getByTestId('pr-back-preview'));
  await within(row).findByTestId('pr-back-status-preview');
  expect(posted).toEqual([{ repositoryId: REPO_OK, version: VERSION_ID, dryRun: true }]);
  expect(within(row).getByText(/would write 1 of 1 file/)).toBeInTheDocument();
  expect(within(row).getByTestId('pr-back-file')).toHaveTextContent('openapi.yaml');
  expect(within(row).getByText(/References schemas another file defines: Invoice/)).toBeInTheDocument();
  expect(within(row).getByTestId('pr-back-body')).toHaveTextContent('rendered from Apiome');
  expect(within(row).queryByTestId('pr-back-link')).not.toBeInTheDocument();
});

test('opening shows the pull request link', async () => {
  syncReply = {
    status: 200,
    body: outcome('opened', { pullRequestNumber: 7, pullRequestUrl: 'https://github.com/acme/users/pull/7' }),
  };
  mount();
  const [row] = await screen.findAllByTestId('pr-back-repository');
  fireEvent.click(within(row).getByTestId('pr-back-open'));
  const link = await within(row).findByTestId('pr-back-link');
  expect(link).toHaveAttribute('href', 'https://github.com/acme/users/pull/7');
  expect(link).toHaveTextContent('View pull request #7');
  expect(posted).toEqual([{ repositoryId: REPO_OK, version: VERSION_ID, dryRun: false }]);
  expect(within(row).getByTestId('pr-back-status-opened')).toHaveTextContent('Pull request opened');
});

test('a refusal is shown in the server words', async () => {
  syncReply = { status: 403, body: { success: false, error: 'Shop is not on the allow list.' } };
  mount();
  const [row] = await screen.findAllByTestId('pr-back-repository');
  fireEvent.click(within(row).getByTestId('pr-back-open'));
  expect(await within(row).findByTestId('pr-back-error')).toHaveTextContent('Shop is not on the allow list.');
});

test('a failed outcome shows its message', async () => {
  syncReply = { status: 200, body: outcome('failed', { files: [], errorMessage: 'Token revoked.' }) };
  mount();
  const [row] = await screen.findAllByTestId('pr-back-repository');
  fireEvent.click(within(row).getByTestId('pr-back-open'));
  await within(row).findByTestId('pr-back-status-failed');
  expect(within(row).getByText('Token revoked.')).toBeInTheDocument();
});

test('renders nothing without repositories, and an error when the list fails', async () => {
  listReply = { status: 200, body: { success: true, repositories: [] } };
  const { container, unmount } = mount();
  await waitFor(() => expect(global.fetch).toHaveBeenCalled());
  expect(container).toBeEmptyDOMElement();
  unmount();

  listReply = { status: 500, body: { success: false, error: 'boom' } };
  mount();
  expect(await screen.findByTestId('pr-back-load-error')).toHaveTextContent('boom');
});
