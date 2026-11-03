/**
 * Per-branch refresh rules (RAR-6.4, #3541): the model and the Settings-tab panel.
 *
 * The model: parsing the flat projection, cadence words and choices, the sentence that says how
 * a tracked branch refreshes, draft validation and the `PUT` body. The panel: it lists every
 * tracked branch with that sentence, edits rules as drafts, enables **Save rules** only when
 * something changed, refuses invalid drafts before calling the server, and re-renders from the
 * server's answer after a save.
 */

import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';

const mockToast = { success: jest.fn(), error: jest.fn() };
jest.mock('@/app/components/ui/toast', () => ({ toast: mockToast }));

import { RepositoryBranchRefreshRules } from '../src/app/components/ade/dashboard/repositories/RepositoryBranchRefreshRules';
import {
  cadenceChoices,
  describeBranchRefresh,
  draftsChanged,
  draftsFromRules,
  draftsToRequest,
  formatCadence,
  newDraft,
  parseBranchRefreshResponse,
  validateDrafts,
} from '../src/app/components/ade/dashboard/repositories/repositoryBranchRefresh';

const REPO_ID = '770e8400-e29b-41d4-a716-446655440002';

/** A minimal fetch response (jsdom has no `Response`). */
function reply(body: unknown, status = 200) {
  return { ok: status >= 200 && status < 300, status, statusText: '', json: async () => body };
}

const PROJECTION = {
  success: true,
  repositoryId: REPO_ID,
  autoRefreshEnabled: true,
  repositoryIntervalSeconds: 3600,
  minIntervalSeconds: 60,
  rules: [
    { branchPattern: 'main', refreshEnabled: true, refreshIntervalSeconds: 300, targetVersionLine: 'latest' },
    { branchPattern: 'sandbox', refreshEnabled: false, refreshIntervalSeconds: null, targetVersionLine: null },
  ],
  branches: [
    { branch: 'main', enabled: true, intervalSeconds: 300, targetVersionLine: 'latest', rulePattern: 'main', lastRefreshedAt: null },
    { branch: 'sandbox', enabled: false, intervalSeconds: 3600, targetVersionLine: null, rulePattern: 'sandbox', lastRefreshedAt: null },
    { branch: 'feature/x', enabled: true, intervalSeconds: 3600, targetVersionLine: null, rulePattern: null, lastRefreshedAt: null },
  ],
};

// ===========================================================================
// Model
// ===========================================================================

describe('repositoryBranchRefresh model', () => {
  it('parses the projection with safe defaults', () => {
    const data = parseBranchRefreshResponse(PROJECTION);
    expect(data.rules[1]).toEqual({
      branchPattern: 'sandbox', refreshEnabled: false, refreshIntervalSeconds: null, targetVersionLine: null,
    });
    expect(data.branches).toHaveLength(3);
    expect(parseBranchRefreshResponse({})).toMatchObject({
      autoRefreshEnabled: true, repositoryIntervalSeconds: 300, minIntervalSeconds: 60, rules: [], branches: [],
    });
  });

  it('words a cadence', () => {
    expect(formatCadence(300)).toBe('5 min');
    expect(formatCadence(3600)).toBe('1 hour');
    expect(formatCadence(21600)).toBe('6 hours');
    expect(formatCadence(86400)).toBe('1 day');
    expect(formatCadence(90)).toBe('90 s');
  });

  it('offers cadences at or above the minimum, plus the current value', () => {
    expect(cadenceChoices(300)).toEqual([300, 900, 3600, 21600, 86400]);
    expect(cadenceChoices(300, 1200)).toEqual([300, 900, 1200, 3600, 21600, 86400]);
  });

  it('describes how a branch refreshes', () => {
    const [main, sandbox, feature] = parseBranchRefreshResponse(PROJECTION).branches;
    expect(describeBranchRefresh(main, true)).toBe('Every 5 min into latest · rule main');
    expect(describeBranchRefresh(sandbox, true)).toBe('Refresh off · rule sandbox');
    expect(describeBranchRefresh(feature, true)).toBe('Every 1 hour · repository settings');
    expect(describeBranchRefresh(main, false)).toBe('Off — auto-refresh is off for the repository');
  });

  it('validates drafts', () => {
    const blank = newDraft();
    expect(validateDrafts([blank])).toMatch(/needs a branch/);
    expect(validateDrafts([{ ...blank, branchPattern: 'rel ease' }])).toMatch(/spaces/);
    expect(validateDrafts([{ ...blank, branchPattern: 'main' }, { ...newDraft(), branchPattern: 'main' }])).toMatch(
      /more than once/
    );
    expect(validateDrafts([{ ...blank, branchPattern: 'main', targetVersionLine: '2/x' }])).toMatch(/Version line/);
    expect(validateDrafts([{ ...blank, branchPattern: 'main', targetVersionLine: '2.x' }])).toBeNull();
  });

  it('round-trips rules through drafts into the PUT body', () => {
    const rules = parseBranchRefreshResponse(PROJECTION).rules;
    const drafts = draftsFromRules(rules);
    expect(draftsToRequest(drafts)).toEqual({ rules });
    expect(draftsChanged(drafts, rules)).toBe(false);
    expect(draftsChanged([...drafts, { ...newDraft(), branchPattern: 'release/*' }], rules)).toBe(true);
  });
});

// ===========================================================================
// Panel
// ===========================================================================

describe('RepositoryBranchRefreshRules', () => {
  let puts: unknown[];

  beforeEach(() => {
    puts = [];
    mockToast.success.mockReset();
    mockToast.error.mockReset();
    global.fetch = jest.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'PUT') {
        const body = JSON.parse(String(init.body));
        puts.push(body);
        return reply({ ...PROJECTION, rules: body.rules });
      }
      return reply(PROJECTION);
    }) as unknown as typeof fetch;
  });

  it('lists every tracked branch with how it refreshes', async () => {
    render(<RepositoryBranchRefreshRules repositoryId={REPO_ID} />);

    const main = await screen.findByTestId('branch-refresh-branch-main');
    expect(main).toHaveTextContent('Every 5 min into latest · rule main');
    expect(within(main).getByText('Refreshes')).toBeInTheDocument();
    expect(screen.getByTestId('branch-refresh-branch-sandbox')).toHaveTextContent('Refresh off · rule sandbox');
    expect(screen.getByTestId('branch-refresh-branch-feature/x')).toHaveTextContent('repository settings');
    expect(global.fetch).toHaveBeenCalledWith(
      `/api/repositories/${REPO_ID}/branch-refresh-rules`,
      expect.objectContaining({ credentials: 'include' })
    );
  });

  it('saves a new rule as part of the whole set', async () => {
    render(<RepositoryBranchRefreshRules repositoryId={REPO_ID} />);
    await screen.findByTestId('branch-refresh');

    const save = screen.getByTestId('branch-refresh-save');
    expect(save).toBeDisabled();

    fireEvent.click(screen.getByRole('button', { name: /Add rule/ }));
    fireEvent.change(screen.getByLabelText('Branch', { selector: '#branch-rule-2-pattern' }), {
      target: { value: 'release/*' },
    });
    fireEvent.change(screen.getByLabelText('Version line', { selector: '#branch-rule-2-line' }), {
      target: { value: '2.x' },
    });
    expect(save).toBeEnabled();
    fireEvent.click(save);

    await waitFor(() => expect(puts).toHaveLength(1));
    expect(puts[0]).toEqual({
      rules: [
        { branchPattern: 'main', refreshEnabled: true, refreshIntervalSeconds: 300, targetVersionLine: 'latest' },
        { branchPattern: 'sandbox', refreshEnabled: false, refreshIntervalSeconds: null, targetVersionLine: null },
        { branchPattern: 'release/*', refreshEnabled: true, refreshIntervalSeconds: null, targetVersionLine: '2.x' },
      ],
    });
    await waitFor(() => expect(mockToast.success).toHaveBeenCalledWith('Branch refresh rules saved.'));
  });

  it('refuses an invalid draft without calling the server', async () => {
    render(<RepositoryBranchRefreshRules repositoryId={REPO_ID} />);
    await screen.findByTestId('branch-refresh');

    fireEvent.click(screen.getByRole('button', { name: /Add rule/ }));
    fireEvent.click(screen.getByTestId('branch-refresh-save'));

    expect(mockToast.error).toHaveBeenCalledWith('Every rule needs a branch name or pattern.');
    expect(puts).toHaveLength(0);
  });

  it('removes a rule', async () => {
    render(<RepositoryBranchRefreshRules repositoryId={REPO_ID} />);
    await screen.findByTestId('branch-refresh');

    fireEvent.click(screen.getByRole('button', { name: 'Remove the rule for sandbox' }));
    fireEvent.click(screen.getByTestId('branch-refresh-save'));

    await waitFor(() => expect(puts).toHaveLength(1));
    expect((puts[0] as { rules: { branchPattern: string }[] }).rules.map((r) => r.branchPattern)).toEqual(['main']);
  });

  it('shows the error with a retry when the read fails', async () => {
    global.fetch = jest.fn(async () => reply({ error: 'repository not found' }, 404)) as unknown as typeof fetch;
    render(<RepositoryBranchRefreshRules repositoryId={REPO_ID} />);
    expect(await screen.findByText('repository not found')).toBeInTheDocument();
  });
});
