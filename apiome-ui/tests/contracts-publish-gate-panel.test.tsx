/**
 * Publish dialog contracts gate panel (PFX-7.3, #6963).
 *
 * The panel is silent unless the gate has something to say (a warning, a block, or a pending
 * verification), shows the per-row reasons, says plainly when publishing is blocked, and fails
 * visibly — with a retry — when the read fails.
 */

import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { ContractsPublishGatePanel } from '../src/app/components/ade/dashboard/ContractsPublishGatePanel';
import {
  contractsGateIsVisible,
  contractsGateStatusLabel,
  type ContractsPublishGate,
} from '../src/app/utils/contracts-publish-gate';

const PROJECT_ID = 'e8d8179b-66f4-4ad4-b462-f7d1c782f8cf';
const VERSION_ID = '71ff5cc0-df6c-48e7-aeb8-32d98df416d1';

const BASE: ContractsPublishGate = {
  policy: 'block',
  status: 'ok',
  triggered: false,
  blocked: false,
  pacticipant: 'billing',
  version: '1.1.0',
  environment: null,
  deployable: true,
  reasons: [],
  counts: {},
  reason: 'contracts-deployable',
  detail: 'Computer says yes.',
  message: 'Computer says yes.',
};

const BLOCKED: ContractsPublishGate = {
  ...BASE,
  status: 'blocked',
  triggered: true,
  blocked: true,
  deployable: false,
  environment: 'prod',
  reasons: [{ type: 'error', code: 'verification-failed', text: 'Verification failed for web' }],
  reason: 'contracts-not-deployable',
  message: 'Publishing is blocked by failing contracts: Verification failed for web',
};

function mockFetch(gate: ContractsPublishGate) {
  global.fetch = jest.fn(() =>
    Promise.resolve({ ok: true, status: 200, json: async () => ({ success: true, ...gate }) })
  ) as unknown as typeof fetch;
}

function mockFailingFetch(message: string) {
  global.fetch = jest.fn(() =>
    Promise.resolve({ ok: false, status: 500, json: async () => ({ success: false, error: message }) })
  ) as unknown as typeof fetch;
}

describe('ContractsPublishGatePanel', () => {
  beforeEach(() => jest.clearAllMocks());

  it('says what it is checking while the read is pending', () => {
    global.fetch = jest.fn(() => new Promise(() => {})) as unknown as typeof fetch;
    render(<ContractsPublishGatePanel projectId={PROJECT_ID} versionId={VERSION_ID} />);
    expect(screen.getByTestId('contracts-publish-gate-loading')).toHaveTextContent('Checking contracts…');
  });

  it('stays silent for a deployable revision', async () => {
    mockFetch(BASE);
    render(<ContractsPublishGatePanel projectId={PROJECT_ID} versionId={VERSION_ID} />);
    await waitFor(() => expect(screen.queryByTestId('contracts-publish-gate-loading')).toBeNull());
    expect(screen.queryByTestId('contracts-publish-gate-panel')).toBeNull();
  });

  it.each(['no-contracts', 'disabled', 'unavailable'] as const)('stays silent for %s', async (status) => {
    mockFetch({ ...BASE, status, deployable: null });
    render(<ContractsPublishGatePanel projectId={PROJECT_ID} versionId={VERSION_ID} />);
    await waitFor(() => expect(screen.queryByTestId('contracts-publish-gate-loading')).toBeNull());
    expect(screen.queryByTestId('contracts-publish-gate-panel')).toBeNull();
  });

  it('surfaces the verdict, the target, the failing rows and the block', async () => {
    mockFetch(BLOCKED);
    render(<ContractsPublishGatePanel projectId={PROJECT_ID} versionId={VERSION_ID} />);

    expect(await screen.findByTestId('contracts-publish-gate-panel')).toBeInTheDocument();
    expect(screen.getByTestId('contracts-publish-gate-status')).toHaveTextContent('Blocked');
    expect(screen.getByText('billing 1.1.0 → prod')).toBeInTheDocument();
    expect(screen.getAllByTestId('contracts-publish-gate-reason')).toHaveLength(1);
    expect(screen.getByText('Verification failed for web', { selector: '.ver-gate__message' })).toBeInTheDocument();
    expect(screen.getByText(/Publishing is blocked by your tenant policy/)).toBeInTheDocument();
  });

  it('warns without claiming a block under the warn policy', async () => {
    mockFetch({ ...BLOCKED, policy: 'warn', status: 'warning', blocked: false, message: 'Contracts need attention.' });
    render(<ContractsPublishGatePanel projectId={PROJECT_ID} versionId={VERSION_ID} />);
    expect(await screen.findByTestId('contracts-publish-gate-status')).toHaveTextContent('Warning');
    expect(screen.queryByText(/Publishing is blocked by your tenant policy/)).toBeNull();
  });

  it('shows a missing verification result as pending, never as a failure', async () => {
    mockFetch({ ...BASE, status: 'pending', deployable: null, message: 'No verification result yet.' });
    render(<ContractsPublishGatePanel projectId={PROJECT_ID} versionId={VERSION_ID} />);
    expect(await screen.findByTestId('contracts-publish-gate-status')).toHaveTextContent('Pending');
    expect(screen.queryByText(/blocked/i)).toBeNull();
  });

  it('says the check failed, with a retry that runs it again', async () => {
    mockFailingFetch('REST API unreachable');
    render(<ContractsPublishGatePanel projectId={PROJECT_ID} versionId={VERSION_ID} />);
    expect(await screen.findByTestId('contracts-publish-gate-error')).toHaveTextContent('REST API unreachable');

    mockFetch(BLOCKED);
    fireEvent.click(screen.getByRole('button', { name: /retry|try again/i }));
    expect(await screen.findByTestId('contracts-publish-gate-panel')).toBeInTheDocument();
  });

  it('does not fetch while the dialog is closed', () => {
    mockFetch(BLOCKED);
    render(<ContractsPublishGatePanel projectId={PROJECT_ID} versionId={VERSION_ID} enabled={false} />);
    expect(global.fetch).not.toHaveBeenCalled();
    expect(screen.queryByTestId('contracts-publish-gate-panel')).toBeNull();
  });

  it('requests the version-scoped proxy route', async () => {
    mockFetch(BLOCKED);
    render(<ContractsPublishGatePanel projectId={PROJECT_ID} versionId={VERSION_ID} />);
    await screen.findByTestId('contracts-publish-gate-panel');
    expect(global.fetch).toHaveBeenCalledWith(
      `/api/projects/${PROJECT_ID}/versions/${VERSION_ID}/contracts-publish-gate`,
      expect.objectContaining({ method: 'GET' })
    );
  });
});

describe('contracts gate helpers', () => {
  it('is visible for a warning, a block or a pending verification only', () => {
    expect(contractsGateIsVisible(BLOCKED)).toBe(true);
    expect(contractsGateIsVisible({ ...BASE, status: 'pending' })).toBe(true);
    expect(contractsGateIsVisible(BASE)).toBe(false);
    expect(contractsGateIsVisible(null)).toBe(false);
  });

  it('labels every status and falls back for an unknown one', () => {
    expect(contractsGateStatusLabel('blocked')).toBe('Blocked');
    expect(contractsGateStatusLabel('ok')).toBe('Deployable');
    expect(contractsGateStatusLabel('mystery')).toBe('Not checked');
  });
});
