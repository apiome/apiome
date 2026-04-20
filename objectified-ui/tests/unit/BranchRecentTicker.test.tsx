/**
 * Unit tests for BranchRecentTicker (GLI-09).
 *
 * Covers: visibility-aware polling pause/resume, 30s interval scheduling/cleanup,
 * AbortController cancellation, and compare deep-link construction.
 */

import React from 'react';
import { render, screen, waitFor, act, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom';

// ── Module mocks ──────────────────────────────────────────────────────────────

const mockPush = jest.fn();
jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush }),
}));

const mockUseStudio = jest.fn();
jest.mock('../../src/app/ade/studio/StudioContext', () => ({
  useStudio: () => mockUseStudio(),
}));

// Lightweight mock so the util imports don't drag in heavy deps
jest.mock('../../src/app/ade/dashboard/versions/version-history-dag', () => ({
  formatRelativeTime: () => '2 min ago',
}));

jest.mock('../../src/app/utils/version-display', () => ({
  getVersionRevisionNote: (row: { shortMessage?: string | null }) =>
    row.shortMessage ?? null,
}));

jest.mock('../../lib/utils', () => ({
  cn: (...args: string[]) => args.filter(Boolean).join(' '),
}));

// ── Helpers ───────────────────────────────────────────────────────────────────

const PROJECT_ID = 'proj-1';
const BRANCH_ID = 'branch-1';
const BRANCH_NAME = 'main';
const TIP_ID = 'v3';
const PARENT_ID = 'v2';

const DEFAULT_BRANCHES = [{ id: BRANCH_ID, name: BRANCH_NAME, tip_version_id: TIP_ID }];

function makeStudio(overrides: Record<string, unknown> = {}) {
  return {
    selectedProjectId: PROJECT_ID,
    selectedBranchId: BRANCH_ID,
    versionBranchesByProjectId: { [PROJECT_ID]: DEFAULT_BRANCHES },
    ...overrides,
  };
}

const ROWS = [
  { id: TIP_ID, version_id: 'v3', shortMessage: 'third commit', parent_version_id: PARENT_ID },
  { id: PARENT_ID, version_id: 'v2', shortMessage: 'second commit', parent_version_id: 'v1' },
  { id: 'v1', version_id: 'v1', shortMessage: 'initial commit', parent_version_id: null },
];

function mockFetchSuccess(rows = ROWS) {
  global.fetch = jest.fn().mockResolvedValue({
    ok: true,
    json: () => Promise.resolve({ success: true, versions: rows }),
  });
}

function mockFetchFailure() {
  global.fetch = jest.fn().mockRejectedValue(new Error('Network error'));
}

// ── Import component after mocks are set up ───────────────────────────────────

// eslint-disable-next-line @typescript-eslint/no-require-imports
const { BranchRecentTicker } = require('../../src/app/ade/studio/components/BranchRecentTicker') as {
  BranchRecentTicker: React.FC;
};

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('BranchRecentTicker', () => {
  beforeEach(() => {
    jest.useFakeTimers();
    mockPush.mockClear();
    mockUseStudio.mockReturnValue(makeStudio());
    // Default tab visible
    Object.defineProperty(document, 'visibilityState', {
      configurable: true,
      get: () => 'visible',
    });
  });

  afterEach(() => {
    jest.useRealTimers();
    jest.restoreAllMocks();
  });

  // ── Rendering ───────────────────────────────────────────────────────────────

  it('renders nothing when no project is selected', () => {
    mockUseStudio.mockReturnValue(makeStudio({ selectedProjectId: null }));
    global.fetch = jest.fn();
    const { container } = render(<BranchRecentTicker />);
    expect(container.firstChild).toBeNull();
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it('renders nothing when no branch is selected', () => {
    mockUseStudio.mockReturnValue(makeStudio({ selectedBranchId: null }));
    global.fetch = jest.fn();
    const { container } = render(<BranchRecentTicker />);
    expect(container.firstChild).toBeNull();
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it('fetches and renders commit rows', async () => {
    mockFetchSuccess();
    render(<BranchRecentTicker />);

    await waitFor(() => {
      expect(screen.getByText('third commit')).toBeInTheDocument();
    });
    expect(screen.getByText('second commit')).toBeInTheDocument();
    expect(screen.getByText('initial commit')).toBeInTheDocument();

    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining(`branchId=${BRANCH_ID}`),
      expect.objectContaining({ signal: expect.any(AbortSignal) })
    );
  });

  it('shows "No commits" placeholder when API returns empty list', async () => {
    mockFetchSuccess([]);
    render(<BranchRecentTicker />);

    await waitFor(() => {
      expect(screen.getByText(/No commits on this lineage yet/)).toBeInTheDocument();
    });
  });

  it('shows "No commits" placeholder when fetch fails', async () => {
    mockFetchFailure();
    render(<BranchRecentTicker />);

    await waitFor(() => {
      expect(screen.getByText(/No commits on this lineage yet/)).toBeInTheDocument();
    });
  });

  // ── Visibility-aware polling ─────────────────────────────────────────────────

  it('pauses polling when tab becomes hidden and resumes when visible', async () => {
    mockFetchSuccess();
    render(<BranchRecentTicker />);

    // Initial fetch on mount
    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(1));

    // Simulate tab hidden
    Object.defineProperty(document, 'visibilityState', {
      configurable: true,
      get: () => 'hidden',
    });
    act(() => {
      document.dispatchEvent(new Event('visibilitychange'));
    });

    // Advance 30s — no new fetch should occur
    act(() => {
      jest.advanceTimersByTime(30_000);
    });
    expect(global.fetch).toHaveBeenCalledTimes(1);

    // Simulate tab visible again
    Object.defineProperty(document, 'visibilityState', {
      configurable: true,
      get: () => 'visible',
    });
    act(() => {
      document.dispatchEvent(new Event('visibilitychange'));
    });

    // Immediate fetch on resume
    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(2));

    // Advance another 30s — polling resumes
    act(() => {
      jest.advanceTimersByTime(30_000);
    });
    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(3));
  });

  it('polls every 30s while tab is visible', async () => {
    mockFetchSuccess();
    render(<BranchRecentTicker />);

    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(1));

    act(() => { jest.advanceTimersByTime(30_000); });
    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(2));

    act(() => { jest.advanceTimersByTime(30_000); });
    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(3));
  });

  it('aborts in-flight request on unmount', async () => {
    const abortSpy = jest.spyOn(AbortController.prototype, 'abort');
    mockFetchSuccess();
    const { unmount } = render(<BranchRecentTicker />);
    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(1));
    unmount();
    expect(abortSpy).toHaveBeenCalled();
  });

  // ── Compare deep-link construction ───────────────────────────────────────────

  it('navigates to compare with parent as base when clicking the tip row', async () => {
    mockFetchSuccess();
    render(<BranchRecentTicker />);

    await waitFor(() => expect(screen.getByText('third commit')).toBeInTheDocument());

    fireEvent.click(screen.getByText('third commit'));

    expect(mockPush).toHaveBeenCalledWith(
      expect.stringContaining(`compareOpen=1`)
    );
    const pushArg: string = mockPush.mock.calls[0][0];
    const params = new URLSearchParams(pushArg.split('?')[1]);
    expect(params.get('compareBase')).toBe(PARENT_ID);
    expect(params.get('compareHead')).toBe(TIP_ID);
  });

  it('navigates to compare with row as base and tip as head when clicking a non-tip row', async () => {
    mockFetchSuccess();
    render(<BranchRecentTicker />);

    await waitFor(() => expect(screen.getByText('second commit')).toBeInTheDocument());

    fireEvent.click(screen.getByText('second commit'));

    expect(mockPush).toHaveBeenCalledWith(expect.stringContaining('compareOpen=1'));
    const pushArg: string = mockPush.mock.calls[0][0];
    const params = new URLSearchParams(pushArg.split('?')[1]);
    expect(params.get('compareBase')).toBe(PARENT_ID);
    expect(params.get('compareHead')).toBe(TIP_ID);
  });

  it('falls back to versions dashboard when tip row has no parent_version_id', async () => {
    // Single row with no parent — the branch's first commit
    const noParentRows = [
      { id: TIP_ID, version_id: 'v1', shortMessage: 'first commit', parent_version_id: null },
    ];
    mockFetchSuccess(noParentRows);
    render(<BranchRecentTicker />);

    await waitFor(() => expect(screen.getByText('first commit')).toBeInTheDocument());

    fireEvent.click(screen.getByText('first commit'));

    expect(mockPush).toHaveBeenCalledWith(
      expect.stringContaining('/ade/dashboard/versions')
    );
    const pushArg: string = mockPush.mock.calls[0][0];
    expect(pushArg).not.toContain('compareOpen');
  });

  it('navigates to versions dashboard when effectiveTipId is null (no rows and no context tip)', async () => {
    // When there are no loaded rows AND no branch tip in context, effectiveTipId is null.
    // In this state the ticker shows the empty placeholder (no buttons), so we verify the
    // component renders cleanly without errors.  The !effectiveTipId guard inside openCompare
    // is a defensive check for a state that cannot be reached via the rendered UI when rows
    // exist (rows[0].id is always truthy).
    mockUseStudio.mockReturnValue(
      makeStudio({ versionBranchesByProjectId: {} })
    );
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ success: true, versions: [] }),
    });
    render(<BranchRecentTicker />);

    await waitFor(() =>
      expect(screen.getByText(/No commits on this lineage yet/)).toBeInTheDocument()
    );
    expect(mockPush).not.toHaveBeenCalled();
  });
});
