/**
 * Recently viewed projects (#510) — the write side and the copy.
 *
 * `dashboard-home-data.test.ts` covers the read that fills Home's panel and
 * `dashboard-home.test.tsx` covers the panel itself. This suite covers the rest:
 *
 * 1. **`recordProjectViewForSession`** — the reader comes from the session, malformed ids never
 *    reach SQL, only live projects in the reader's workspaces match, and a failure is a `false`
 *    rather than a rejection the Versions page would have to catch.
 * 2. **`useRecordProjectView`** — only a project the reader chose is recorded (not the Versions
 *    page's first-project fallback), once per project per mount.
 * 3. **`recentlyViewedLine`** — the row's quiet line.
 */

import { renderHook } from '@testing-library/react';

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

// The hook's tests below mock this module; the action's own tests need the real one.
const { recordProjectViewForSession } = jest.requireActual<
  typeof import('../lib/db/project-views')
>('../lib/db/project-views');
import { projectToRecord, useRecordProjectView } from '@/app/hooks/useRecordProjectView';
import { recentlyViewedLine } from '@/app/components/ade/dashboard/home/homeModel';

const PROJECT_ID = '11111111-1111-4111-8111-111111111111';
const OTHER_ID = '22222222-2222-4222-8222-222222222222';

beforeEach(() => {
  queries.length = 0;
  mockQuery.mockClear();
  (getAuthSession as jest.Mock).mockReset();
  (getAuthSession as jest.Mock).mockResolvedValue({ user: { user_id: 'user-1' } });
  jest.spyOn(console, 'error').mockImplementation(() => undefined);
});

afterEach(() => {
  jest.restoreAllMocks();
});

/* -------------------------------------------------------------------------
   1. recordProjectViewForSession
   ------------------------------------------------------------------------- */

describe('recordProjectViewForSession', () => {
  it('upserts the session reader view of a live project in one of their workspaces', async () => {
    await expect(recordProjectViewForSession(PROJECT_ID)).resolves.toBe(true);

    expect(queries).toHaveLength(1);
    const [{ sql, params }] = queries;
    expect(params).toEqual(['user-1', PROJECT_ID]);
    expect(sql).toContain('INSERT INTO apiome.project_views');
    expect(sql).toContain('p.deleted_at IS NULL');
    expect(sql).toContain('FROM apiome.tenant_users WHERE user_id = $1');
    expect(sql).toContain('ON CONFLICT (user_id, project_id) DO UPDATE');
    expect(sql).toContain('view_count = apiome.project_views.view_count + 1');
    expect(sql).not.toContain('user-1');
  });

  it('reports false when no row matched (unknown, deleted or foreign project)', async () => {
    mockQuery.mockResolvedValueOnce({ rows: [], rowCount: 0 });
    await expect(recordProjectViewForSession(PROJECT_ID)).resolves.toBe(false);
  });

  it.each(['', 'not-a-uuid', `${PROJECT_ID}'; DROP TABLE x; --`])(
    'refuses %p without touching the database',
    async (value) => {
      await expect(recordProjectViewForSession(value)).resolves.toBe(false);
      expect(queries).toHaveLength(0);
    },
  );

  it('records nothing without a signed-in reader', async () => {
    (getAuthSession as jest.Mock).mockResolvedValue(null);
    await expect(recordProjectViewForSession(PROJECT_ID)).resolves.toBe(false);
    expect(queries).toHaveLength(0);
  });

  it('survives a session lookup that throws', async () => {
    (getAuthSession as jest.Mock).mockRejectedValue(new Error('no cookies'));
    await expect(recordProjectViewForSession(PROJECT_ID)).resolves.toBe(false);
  });

  it('turns a database failure into false, and logs it', async () => {
    mockQuery.mockRejectedValueOnce(new Error('relation "project_views" does not exist'));
    await expect(recordProjectViewForSession(PROJECT_ID)).resolves.toBe(false);
    expect(console.error).toHaveBeenCalledWith(
      expect.stringContaining('project-views'),
      expect.any(Error),
    );
  });
});

/* -------------------------------------------------------------------------
   2. useRecordProjectView
   ------------------------------------------------------------------------- */

jest.mock('@lib/db/project-views', () => ({
  recordProjectViewForSession: (projectId: string) => mockRecord(projectId),
}));
const mockRecord = jest.fn((projectId: string) => Promise.resolve(Boolean(projectId)));

describe('projectToRecord', () => {
  it('records the selected project when the URL names it', () => {
    expect(projectToRecord({ urlProjectId: PROJECT_ID, selectedProjectId: PROJECT_ID })).toBe(
      PROJECT_ID,
    );
  });

  it('records nothing for the first-project fallback (no projectId in the URL)', () => {
    expect(projectToRecord({ urlProjectId: null, selectedProjectId: PROJECT_ID })).toBeNull();
  });

  it('records nothing while the URL and the selection disagree', () => {
    expect(projectToRecord({ urlProjectId: OTHER_ID, selectedProjectId: PROJECT_ID })).toBeNull();
  });

  it('records nothing before a project is selected', () => {
    expect(projectToRecord({ urlProjectId: PROJECT_ID, selectedProjectId: null })).toBeNull();
  });
});

describe('useRecordProjectView', () => {
  beforeEach(() => mockRecord.mockClear());

  it('records each opened project once, and again after switching back', () => {
    const { rerender } = renderHook((props) => useRecordProjectView(props), {
      initialProps: { urlProjectId: PROJECT_ID, selectedProjectId: PROJECT_ID } as {
        urlProjectId: string | null;
        selectedProjectId: string | null;
      },
    });
    expect(mockRecord).toHaveBeenCalledTimes(1);
    expect(mockRecord).toHaveBeenLastCalledWith(PROJECT_ID);

    // A re-render on the same project adds nothing.
    rerender({ urlProjectId: PROJECT_ID, selectedProjectId: PROJECT_ID });
    expect(mockRecord).toHaveBeenCalledTimes(1);

    rerender({ urlProjectId: OTHER_ID, selectedProjectId: OTHER_ID });
    expect(mockRecord).toHaveBeenCalledTimes(2);
    expect(mockRecord).toHaveBeenLastCalledWith(OTHER_ID);

    rerender({ urlProjectId: PROJECT_ID, selectedProjectId: PROJECT_ID });
    expect(mockRecord).toHaveBeenCalledTimes(3);
  });

  it('records nothing for the fallback selection', () => {
    renderHook(() => useRecordProjectView({ urlProjectId: null, selectedProjectId: PROJECT_ID }));
    expect(mockRecord).not.toHaveBeenCalled();
  });

  it('swallows a rejected record so the page never sees it', async () => {
    mockRecord.mockRejectedValueOnce(new Error('offline'));
    expect(() =>
      renderHook(() =>
        useRecordProjectView({ urlProjectId: PROJECT_ID, selectedProjectId: PROJECT_ID }),
      ),
    ).not.toThrow();
    await Promise.resolve();
  });
});

/* -------------------------------------------------------------------------
   3. recentlyViewedLine
   ------------------------------------------------------------------------- */

describe('recentlyViewedLine', () => {
  const NOW = new Date('2026-10-21T15:00:00.000Z');

  it('names the revision, when it was viewed and how often', () => {
    expect(recentlyViewedLine('v2.4.0', '2026-10-21T13:00:00.000Z', 5, NOW)).toBe(
      'v2.4.0 · Viewed 2 hours ago · 5 views',
    );
  });

  it('leaves the count out after a single view', () => {
    expect(recentlyViewedLine('v1.0.0', '2026-10-21T14:59:30.000Z', 1, NOW)).toBe(
      'v1.0.0 · Viewed just now',
    );
  });

  it('says so when the project has no revisions', () => {
    expect(recentlyViewedLine(null, '2026-10-18T15:00:00.000Z', 2, NOW)).toBe(
      'No versions yet · Viewed 3 days ago · 2 views',
    );
  });
});
