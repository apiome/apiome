/**
 * Deferred fidelity scoring of the export targets list.
 *
 * A large source lists its export targets at once (`fidelity=deferred`) with no badges, then
 * `useExportTargets` polls `/api/export/targets/fidelity/{token}` and swaps the scored list in.
 * Covers the hook (pending → ready, an unknown job falling back to an inline load, a failed job),
 * {@link pollTargetFidelity} on its own, and the "Scoring…" badge on an unscored card.
 */
import { act, render, renderHook, screen, waitFor } from '@testing-library/react';
import {
  FIDELITY_POLL_MS,
  pollTargetFidelity,
  readLastTargets,
  useExportTargets,
} from '../src/app/components/ade/dashboard/export/useExportTargets';
import { MultiTargetChecklist } from '../src/app/components/ade/dashboard/export/MultiTargetChecklist';
import {
  exportTargetCards,
  fidelityPreSummary,
  SCORING_LABEL,
  type ExportTargetEntry,
  type ExportTargetsResponse,
  type TargetFidelitySummary,
} from '../src/app/components/ade/dashboard/export/exportTargetCatalog';
import {
  fidelityBadgeLabel,
  isRecentExport,
} from '../src/app/components/ade/dashboard/export/recentExports';

const LOSSLESS: TargetFidelitySummary = {
  tier: 'lossless',
  preserved_percent: 100,
  total: 1,
  preserved: 1,
  dropped: 0,
  approximated: 0,
  synthesized: 0,
};

function entry(key: string, fidelity: TargetFidelitySummary | null): ExportTargetEntry {
  return {
    descriptor: {
      key,
      format: key,
      label: key.toUpperCase(),
      description: `Export as ${key}.`,
      icon: 'file-json',
      paradigm: 'rest',
      multi_file: false,
      needs_toolchain: false,
      available: true,
      unavailable_reason: null,
    },
    capability_profile: { operations: true },
    options_schema: { properties: {} },
    default_options: {},
    fidelity,
  } as ExportTargetEntry;
}

const PENDING: ExportTargetsResponse = {
  artifact: 'proj-1',
  version: null,
  version_record_id: 'rev-1',
  version_label: '1.0.0',
  targets: [entry('openapi', null), entry('graphql', null)],
  fidelity_status: 'pending',
  fidelity_token: 'tok-1',
};
const SCORED = [
  entry('openapi', LOSSLESS),
  entry('graphql', { ...LOSSLESS, tier: 'lossy', preserved_percent: 80 }),
];

type Answer = { status: number; body: unknown };

/** A fetch mock answering by URL prefix (longest first), recording every URL. */
function mockFetch(routes: Record<string, Answer | (() => Answer)>) {
  const calls: string[] = [];
  global.fetch = jest.fn((input: unknown) => {
    const url = String(input);
    calls.push(url);
    const match = Object.keys(routes)
      .sort((a, b) => b.length - a.length)
      .find((prefix) => url.startsWith(prefix));
    const route = match ? routes[match] : { status: 404, body: { success: false } };
    const answer = typeof route === 'function' ? route() : route;
    return Promise.resolve({
      ok: answer.status < 400,
      status: answer.status,
      json: () => Promise.resolve(answer.body),
    });
  }) as unknown as typeof fetch;
  return calls;
}

beforeEach(() => {
  window.sessionStorage.clear();
  jest.useFakeTimers();
});

afterEach(() => {
  jest.useRealTimers();
});

/** Let one poll interval pass and its fetch settle. */
async function tick() {
  await act(async () => {
    await jest.advanceTimersByTimeAsync(FIDELITY_POLL_MS);
  });
}

describe('useExportTargets with deferred scoring', () => {
  it('shows the unscored list at once, then swaps in the scores', async () => {
    let polls = 0;
    const calls = mockFetch({
      '/api/export/targets?': { status: 200, body: { success: true, ...PENDING } },
      '/api/export/targets/fidelity/tok-1': () => {
        polls += 1;
        return polls < 2
          ? { status: 200, body: { success: true, status: 'pending', targets: null, error: null } }
          : { status: 200, body: { success: true, status: 'ready', targets: SCORED, error: null } };
      },
    });
    const { result } = renderHook(() => useExportTargets(true, 'proj-1', null));

    await waitFor(() => expect(result.current.response?.targets).toHaveLength(2));
    expect(calls[0]).toContain('fidelity=deferred');
    expect(result.current.loading).toBe(false);
    expect(result.current.scoring).toBe(true);
    expect(result.current.response?.targets.every((t) => t.fidelity === null)).toBe(true);
    // An unscored list is not remembered as the session's last good one.
    expect(readLastTargets('proj-1', null)).toBeNull();

    await tick();
    expect(result.current.scoring).toBe(true);
    await tick();
    await waitFor(() => expect(result.current.scoring).toBe(false));
    expect(result.current.response?.targets.map((t) => t.fidelity?.tier)).toEqual([
      'lossless',
      'lossy',
    ]);
    expect(result.current.response?.fidelity_status).toBe('ready');
    expect(result.current.scoringError).toBeNull();
    expect(readLastTargets('proj-1', null)?.response.targets[0].fidelity?.tier).toBe('lossless');
  });

  it('does not poll a list that came back scored', async () => {
    const calls = mockFetch({
      '/api/export/targets?': {
        status: 200,
        body: {
          success: true,
          ...PENDING,
          targets: SCORED,
          fidelity_status: 'ready',
          fidelity_token: null,
        },
      },
    });
    const { result } = renderHook(() => useExportTargets(true, 'proj-1', null));
    await waitFor(() =>
      expect(result.current.response?.targets[0].fidelity?.tier).toBe('lossless'),
    );
    await tick();
    expect(result.current.scoring).toBe(false);
    expect(calls.filter((url) => url.includes('/fidelity/'))).toHaveLength(0);
  });

  it('loads the scored list outright when the server no longer knows the job', async () => {
    const calls = mockFetch({
      '/api/export/targets?artifact=proj-1&fidelity=deferred': {
        status: 200,
        body: { success: true, ...PENDING },
      },
      '/api/export/targets?artifact=proj-1': {
        status: 200,
        body: {
          success: true,
          ...PENDING,
          targets: SCORED,
          fidelity_status: 'ready',
          fidelity_token: null,
        },
      },
      '/api/export/targets/fidelity/tok-1': {
        status: 404,
        body: { success: false, error: 'not known', code: 'fidelity-job-unknown' },
      },
    });
    const { result } = renderHook(() => useExportTargets(true, 'proj-1', null));
    await waitFor(() => expect(result.current.scoring).toBe(true));
    await tick();
    await waitFor(() => expect(result.current.scoring).toBe(false));
    expect(result.current.response?.targets[1].fidelity?.preserved_percent).toBe(80);
    expect(calls).toContain('/api/export/targets?artifact=proj-1');
  });

  it('keeps the unscored list usable when scoring fails', async () => {
    mockFetch({
      '/api/export/targets?': { status: 200, body: { success: true, ...PENDING } },
      '/api/export/targets/fidelity/tok-1': {
        status: 200,
        body: { success: true, status: 'failed', targets: null, error: 'out of memory' },
      },
    });
    const { result } = renderHook(() => useExportTargets(true, 'proj-1', null));
    await waitFor(() => expect(result.current.scoring).toBe(true));
    await tick();
    await waitFor(() => expect(result.current.scoring).toBe(false));
    expect(result.current.scoringError).toBe('out of memory');
    expect(result.current.error).toBeNull();
    expect(result.current.response?.targets).toHaveLength(2);
  });
});

describe('pollTargetFidelity', () => {
  const noWait = () => Promise.resolve();

  it('stops as soon as it is cancelled', async () => {
    const calls = mockFetch({});
    await expect(pollTargetFidelity('tok-1', () => true, noWait)).resolves.toEqual({
      kind: 'cancelled',
    });
    expect(calls).toHaveLength(0);
  });

  it('gives up after repeated network failures', async () => {
    global.fetch = jest.fn(() => Promise.reject(new Error('offline'))) as unknown as typeof fetch;
    const outcome = await pollTargetFidelity('tok-1', () => false, noWait);
    expect(outcome.kind).toBe('failed');
  });
});

describe('an unscored card', () => {
  it('shows Scoring… on the multi-target checklist', () => {
    const cards = exportTargetCards({ ...PENDING });
    render(
      <MultiTargetChecklist cards={cards} selected={[]} onToggle={() => undefined} minimum={2} />,
    );
    expect(screen.getAllByText(SCORING_LABEL)).toHaveLength(2);
  });

  it('is in neither pre-summary row until it is scored', () => {
    const { best, lossy } = fidelityPreSummary(exportTargetCards({ ...PENDING }));
    expect(best).toHaveLength(0);
    expect(lossy).toHaveLength(0);
  });

  it('records a recent export with no score yet', () => {
    const record = {
      targetKey: 'openapi',
      targetLabel: 'OpenAPI',
      tier: null,
      preservedPercent: null,
      filename: 'a.json',
      exportedAt: Date.now(),
    };
    expect(isRecentExport(record)).toBe(true);
    expect(fidelityBadgeLabel(record)).toBe('fidelity not scored');
  });
});
