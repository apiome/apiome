/**
 * Time spent per project (#544) — the heartbeat and the tracker that sends it.
 *
 * `dashboard-home-data.test.ts` covers the read behind Home's panel, `dashboard-home-model.test.ts`
 * the bars and durations, and `dashboard-home.test.tsx` the panel. This suite covers the write:
 *
 * 1. **`recordProjectTimeForSession`** — the reader is the session, only live projects in their
 *    workspaces are credited, the rate limit and the day cap are in the statement, and a failure
 *    is `false`.
 * 2. **`shouldBeat` / `useProjectTimeTracker`** — a heartbeat a minute, only while a project is
 *    open, the tab is visible and the reader was active in the last five minutes.
 */

import { act, renderHook } from '@testing-library/react';

import { getAuthSession } from './__mocks__/server-session';

/** Every `connectionPool.query` call, in order. */
const queries: { sql: string; params: unknown[] }[] = [];
const mockQuery = jest.fn((sql: string, params: unknown[]) => {
  queries.push({ sql, params });
  return Promise.resolve({ rows: [], rowCount: 1 });
});

jest.mock('../lib/db/db', () => ({
  query: (sql: string, params: unknown[]) => mockQuery(sql, params),
}));

// The hook's tests mock the action; the action's own tests need the real one.
const { recordProjectTimeForSession } = jest.requireActual<typeof import('../lib/db/project-time')>(
  '../lib/db/project-time'
);

const mockBeat = jest.fn((projectId: string) => Promise.resolve(Boolean(projectId)));
jest.mock('@lib/db/project-time', () => ({
  recordProjectTimeForSession: (projectId: string) => mockBeat(projectId),
}));

import {
  BEAT_INTERVAL_MS,
  IDLE_AFTER_MS,
  shouldBeat,
  useProjectTimeTracker,
} from '@/app/hooks/useProjectTimeTracker';

const PROJECT_ID = '11111111-1111-4111-8111-111111111111';
const OTHER_ID = '22222222-2222-4222-8222-222222222222';

beforeEach(() => {
  queries.length = 0;
  mockQuery.mockClear();
  mockBeat.mockClear();
  (getAuthSession as jest.Mock).mockReset();
  (getAuthSession as jest.Mock).mockResolvedValue({ user: { user_id: 'user-1' } });
  jest.spyOn(console, 'error').mockImplementation(() => undefined);
});

afterEach(() => {
  jest.restoreAllMocks();
  jest.useRealTimers();
});

/* -------------------------------------------------------------------------
   1. recordProjectTimeForSession
   ------------------------------------------------------------------------- */

describe('recordProjectTimeForSession', () => {
  it('credits a minute to the reader, today, for a live project in one of their workspaces', async () => {
    await expect(recordProjectTimeForSession(PROJECT_ID)).resolves.toBe(true);

    const [{ sql, params }] = queries;
    expect(params).toEqual(['user-1', PROJECT_ID, 60, 55, 86_400]);
    expect(sql).toContain('INSERT INTO apiome.project_time');
    expect(sql).toContain("(CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::date");
    expect(sql).toContain('p.deleted_at IS NULL');
    expect(sql).toContain('FROM apiome.tenant_users WHERE user_id = $1::uuid');
    expect(sql).not.toContain('user-1');
  });

  it('rate-limits in the statement and caps the day at 24 hours', async () => {
    await recordProjectTimeForSession(PROJECT_ID);
    const [{ sql }] = queries;
    expect(sql).toContain('ON CONFLICT (user_id, project_id, day) DO UPDATE');
    expect(sql).toContain('LEAST($5::int, apiome.project_time.active_seconds + $3::int)');
    expect(sql).toContain('last_beat_at <= CURRENT_TIMESTAMP - make_interval(secs => $4::int)');
  });

  it('reports false when the beat came too soon or the project is out of reach', async () => {
    mockQuery.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    await expect(recordProjectTimeForSession(PROJECT_ID)).resolves.toBe(false);
  });

  it.each(['', 'nope', `${PROJECT_ID}'--`])('refuses %p without touching the database', async (id) => {
    await expect(recordProjectTimeForSession(id)).resolves.toBe(false);
    expect(queries).toHaveLength(0);
  });

  it('credits nothing without a signed-in reader', async () => {
    (getAuthSession as jest.Mock).mockResolvedValue(null);
    await expect(recordProjectTimeForSession(PROJECT_ID)).resolves.toBe(false);
    expect(queries).toHaveLength(0);
  });

  it('turns a database failure into false, and logs it', async () => {
    mockQuery.mockRejectedValueOnce(new Error('down'));
    await expect(recordProjectTimeForSession(PROJECT_ID)).resolves.toBe(false);
    expect(console.error).toHaveBeenCalledWith(expect.stringContaining('project-time'), expect.any(Error));
  });
});

/* -------------------------------------------------------------------------
   2. shouldBeat and useProjectTimeTracker
   ------------------------------------------------------------------------- */

describe('shouldBeat', () => {
  const NOW = 1_000_000_000;

  it('beats for an open project in a visible tab with recent input', () => {
    expect(shouldBeat({ projectId: PROJECT_ID, visible: true, lastActivityAt: NOW - 1000, now: NOW })).toBe(true);
    expect(
      shouldBeat({ projectId: PROJECT_ID, visible: true, lastActivityAt: NOW - IDLE_AFTER_MS, now: NOW })
    ).toBe(true);
  });

  it('does not beat with no project, a hidden tab, or an idle reader', () => {
    expect(shouldBeat({ projectId: null, visible: true, lastActivityAt: NOW, now: NOW })).toBe(false);
    expect(shouldBeat({ projectId: PROJECT_ID, visible: false, lastActivityAt: NOW, now: NOW })).toBe(false);
    expect(
      shouldBeat({ projectId: PROJECT_ID, visible: true, lastActivityAt: NOW - IDLE_AFTER_MS - 1, now: NOW })
    ).toBe(false);
  });
});

describe('useProjectTimeTracker', () => {
  /** Pretend the tab is visible or hidden. */
  function setVisibility(state: 'visible' | 'hidden') {
    Object.defineProperty(document, 'visibilityState', { value: state, configurable: true });
  }

  beforeEach(() => {
    jest.useFakeTimers();
    setVisibility('visible');
  });

  it('beats once a minute while the reader is active, for the open project', () => {
    renderHook(() => useProjectTimeTracker(PROJECT_ID));
    expect(mockBeat).not.toHaveBeenCalled();

    act(() => {
      jest.advanceTimersByTime(BEAT_INTERVAL_MS);
    });
    expect(mockBeat).toHaveBeenCalledTimes(1);
    expect(mockBeat).toHaveBeenLastCalledWith(PROJECT_ID);

    act(() => {
      window.dispatchEvent(new Event('keydown'));
      jest.advanceTimersByTime(BEAT_INTERVAL_MS);
    });
    expect(mockBeat).toHaveBeenCalledTimes(2);
  });

  it('stops counting after five idle minutes, and resumes on input', () => {
    renderHook(() => useProjectTimeTracker(PROJECT_ID));

    act(() => {
      jest.advanceTimersByTime(IDLE_AFTER_MS + 2 * BEAT_INTERVAL_MS);
    });
    // The first five minutes after opening count; the idle ones after do not.
    expect(mockBeat).toHaveBeenCalledTimes(5);

    act(() => {
      window.dispatchEvent(new Event('pointerdown'));
      jest.advanceTimersByTime(BEAT_INTERVAL_MS);
    });
    expect(mockBeat).toHaveBeenCalledTimes(6);
  });

  it('counts nothing while the tab is hidden', () => {
    renderHook(() => useProjectTimeTracker(PROJECT_ID));
    setVisibility('hidden');
    act(() => {
      jest.advanceTimersByTime(3 * BEAT_INTERVAL_MS);
    });
    expect(mockBeat).not.toHaveBeenCalled();
  });

  it('follows the open project, and stops with none', () => {
    const { rerender } = renderHook(({ id }: { id: string | null }) => useProjectTimeTracker(id), {
      initialProps: { id: PROJECT_ID as string | null },
    });
    rerender({ id: OTHER_ID });
    act(() => {
      jest.advanceTimersByTime(BEAT_INTERVAL_MS);
    });
    expect(mockBeat).toHaveBeenCalledTimes(1);
    expect(mockBeat).toHaveBeenLastCalledWith(OTHER_ID);

    rerender({ id: null });
    act(() => {
      jest.advanceTimersByTime(3 * BEAT_INTERVAL_MS);
    });
    expect(mockBeat).toHaveBeenCalledTimes(1);
  });

  it('stops on unmount', () => {
    const { unmount } = renderHook(() => useProjectTimeTracker(PROJECT_ID));
    unmount();
    act(() => {
      jest.advanceTimersByTime(3 * BEAT_INTERVAL_MS);
    });
    expect(mockBeat).not.toHaveBeenCalled();
  });
});
