/**
 * The repository's PR-back settings card (REPO-5.8, #2793), rendered.
 *
 * Mounts the real `RepositoryPrBackSettings` against a mocked BFF: an unconfigured repository
 * reads as off, the form saves the policy, ticked projects, target branch, template and the
 * reviewers as typed, and re-renders from what the server returns; a refusal is shown.
 */

import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';

import { RepositoryPrBackSettings } from '../src/app/components/ade/dashboard/repositories/RepositoryPrBackSettings';

const REPO = '66666666-6666-4666-8666-666666666666';
const SHOP = '22222222-2222-4222-8222-222222222222';
const BILLING = '22222222-2222-4222-8222-222222222223';
const GONE = '22222222-2222-4222-8222-222222222224';

const UNCONFIGURED = {
  success: true,
  repositoryId: REPO,
  configured: false,
  projectPolicy: 'allow',
  projects: [],
  targetBranch: null,
  commitMessageTemplate: null,
  defaultCommitMessageTemplate: 'Sync {{project}} {{version}} from Apiome',
  reviewers: [],
};

let settingsReply: { status: number; body: unknown };
let saveReply: { status: number; body: unknown };
let saved: unknown[];

beforeEach(() => {
  saved = [];
  settingsReply = { status: 200, body: UNCONFIGURED };
  saveReply = {
    status: 200,
    body: {
      ...UNCONFIGURED,
      configured: true,
      projectPolicy: 'deny',
      projects: [{ id: BILLING, name: 'Billing' }],
      targetBranch: 'develop',
      reviewers: ['octocat', 'acme/api'],
    },
  };
  global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url === '/api/projects') {
      return {
        ok: true,
        status: 200,
        json: async () => ({ success: true, projects: [{ id: SHOP, name: 'Shop' }, { id: BILLING, name: 'Billing' }] }),
      } as unknown as Response;
    }
    if (init?.method === 'PUT') {
      saved.push(JSON.parse(String(init.body)));
      return { ok: saveReply.status < 400, status: saveReply.status, json: async () => saveReply.body } as unknown as Response;
    }
    return {
      ok: settingsReply.status < 400,
      status: settingsReply.status,
      json: async () => settingsReply.body,
    } as unknown as Response;
  }) as unknown as typeof fetch;
});

test('an unconfigured repository reads as off', async () => {
  render(<RepositoryPrBackSettings repositoryId={REPO} />);
  expect(await screen.findByTestId('pr-back-settings-summary')).toHaveTextContent(/PR-back is off/);
  expect(screen.getByTestId('pr-back-configured')).toHaveTextContent('Off');
  expect(screen.getByTestId('pr-back-policy-allow')).toBeChecked();
  expect(screen.getByTestId('pr-back-template')).toHaveAttribute(
    'placeholder',
    'Sync {{project}} {{version}} from Apiome',
  );
  expect(screen.getAllByTestId('pr-back-project')).toHaveLength(2);
});

test('saving sends every field and re-renders from the reply', async () => {
  render(<RepositoryPrBackSettings repositoryId={REPO} />);
  await screen.findByTestId('pr-back-settings-form');
  fireEvent.click(screen.getByTestId('pr-back-policy-deny'));
  fireEvent.click(screen.getByLabelText('Billing'));
  fireEvent.change(screen.getByTestId('pr-back-target-branch'), { target: { value: 'develop' } });
  fireEvent.change(screen.getByTestId('pr-back-reviewers'), { target: { value: '@octocat, acme/api octocat' } });
  fireEvent.change(screen.getByTestId('pr-back-template'), { target: { value: 'api: {{project}}' } });
  fireEvent.click(screen.getByTestId('pr-back-save'));

  await waitFor(() => expect(screen.getByText('Saved.')).toBeInTheDocument());
  expect(saved).toEqual([
    {
      projectPolicy: 'deny',
      projectIds: [BILLING],
      targetBranch: 'develop',
      commitMessageTemplate: 'api: {{project}}',
      reviewers: ['octocat', 'acme/api'],
    },
  ]);
  expect(screen.getByTestId('pr-back-configured')).toHaveTextContent('On');
  expect(screen.getByTestId('pr-back-settings-summary')).toHaveTextContent(
    'Every project except 1 may open pull requests into develop.',
  );
  expect(screen.getByTestId('pr-back-reviewers')).toHaveValue('octocat, acme/api');
});

test('a listed project the picker does not show stays visible', async () => {
  settingsReply = {
    status: 200,
    body: { ...UNCONFIGURED, configured: true, projects: [{ id: GONE, name: null }] },
  };
  render(<RepositoryPrBackSettings repositoryId={REPO} />);
  expect(await screen.findByLabelText(`Deleted project ${GONE}`)).toBeChecked();
});

test('a refused save and a failed load are shown', async () => {
  saveReply = { status: 422, body: { success: false, error: "Reviewer 'two words' is neither a GitHub login" } };
  const { unmount } = render(<RepositoryPrBackSettings repositoryId={REPO} />);
  await screen.findByTestId('pr-back-settings-form');
  fireEvent.click(screen.getByTestId('pr-back-save'));
  expect(await screen.findByTestId('pr-back-settings-error')).toHaveTextContent(/neither a GitHub login/);
  unmount();

  settingsReply = { status: 403, body: { success: false, error: 'Forbidden' } };
  render(<RepositoryPrBackSettings repositoryId={REPO} />);
  expect(await screen.findByTestId('pr-back-settings-error')).toHaveTextContent('Forbidden');
  expect(screen.queryByTestId('pr-back-settings-form')).not.toBeInTheDocument();
});
