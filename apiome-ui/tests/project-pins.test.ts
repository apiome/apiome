/**
 * Pinned projects (#513) — the server actions and the toast copy.
 *
 * `dashboard-home-data.test.ts` covers the read that fills Home's panel, `dashboard-home.test.tsx`
 * the panel and its unpin button, and `projects-hive-redesign.test.tsx` the ⋯ menu items. This
 * suite covers the writes:
 *
 * 1. **The reader is the session**, and malformed ids never reach SQL.
 * 2. **Only live projects in the reader's workspaces can be pinned.**
 * 3. **The limit holds** — checked inside one transaction, under the advisory lock REST takes, and
 *    an existing pin is reported as such even at the limit.
 * 4. **Every failure is a status**, with the transaction rolled back and the client released.
 */

import { getAuthSession } from './__mocks__/server-session';

/** Every statement the pooled client ran, in order. */
const statements: { sql: string; params: unknown[] }[] = [];

/** How the scripted client answers each statement. */
const script = {
  projectTenant: 'tenant-1' as string | null,
  existing: false,
  count: 0,
  failOn: null as string | null,
};

const release = jest.fn();

/** A pooled client that answers from {@link script}. */
const client = {
  query: jest.fn(async (sql: string, params: unknown[] = []) => {
    statements.push({ sql, params });
    if (script.failOn && sql.includes(script.failOn)) throw new Error('database said no');
    if (sql.includes('SELECT p.tenant_id')) {
      return { rows: script.projectTenant ? [{ tenant_id: script.projectTenant }] : [] };
    }
    if (sql.includes('SELECT 1 FROM apiome.project_pins')) {
      return { rows: script.existing ? [{ '?column?': 1 }] : [] };
    }
    if (sql.includes('COUNT(*)')) return { rows: [{ n: String(script.count) }] };
    return { rows: [], rowCount: 1 };
  }),
  release,
};

/** Statements sent straight to the pool (the list and the unpin). */
const poolQueries: { sql: string; params: unknown[] }[] = [];
const mockPoolQuery = jest.fn(async (sql: string, params: unknown[]) => {
  poolQueries.push({ sql, params });
  return {
    rows: [
      { project_id: 'p-1', project_name: 'Orders', pinned_at: new Date('2026-10-21T10:00:00Z'), version_id: 'v1.0.0' },
      { project_id: 'p-2', project_name: 'Billing', pinned_at: '2026-10-20T10:00:00Z', version_id: null },
    ],
    rowCount: 1,
  };
});
const mockConnect = jest.fn(async () => client);

jest.mock('../lib/db/db', () => ({
  query: (sql: string, params: unknown[]) => mockPoolQuery(sql, params),
  connect: () => mockConnect(),
}));

import {
  listPinnedProjectIdsForSession,
  listPinnedProjectsForSession,
  pinProjectForSession,
  unpinProjectForSession,
} from '../lib/db/project-pins';
import { pinToast } from '@/app/hooks/useProjectPins';

const PROJECT_ID = '11111111-1111-4111-8111-111111111111';

/** The SQL of every statement, for "did it write?" checks. */
const sqlRun = () => statements.map((entry) => entry.sql);

beforeEach(() => {
  statements.length = 0;
  poolQueries.length = 0;
  Object.assign(script, { projectTenant: 'tenant-1', existing: false, count: 0, failOn: null });
  jest.clearAllMocks();
  (getAuthSession as jest.Mock).mockResolvedValue({
    user: { user_id: 'user-1', current_tenant_id: 'tenant-1' },
  });
  jest.spyOn(console, 'error').mockImplementation(() => undefined);
});

afterEach(() => {
  jest.restoreAllMocks();
});

/* -------------------------------------------------------------------------
   pinProjectForSession
   ------------------------------------------------------------------------- */

describe('pinProjectForSession', () => {
  it('pins under the limit, in one transaction, after taking the shared lock', async () => {
    script.count = 3;
    await expect(pinProjectForSession(PROJECT_ID)).resolves.toBe('pinned');

    const sql = sqlRun();
    expect(sql[0]).toBe('BEGIN');
    expect(sql.at(-1)).toBe('COMMIT');
    const lock = statements.find((entry) => entry.sql.includes('pg_advisory_xact_lock'));
    expect(lock?.params).toEqual(['project_pins:user-1:tenant-1']);
    const insert = statements.find((entry) => entry.sql.includes('INSERT INTO apiome.project_pins'));
    expect(insert?.params).toEqual(['user-1', PROJECT_ID, 'tenant-1']);
    expect(release).toHaveBeenCalledTimes(1);
  });

  it('looks the project up through the reader membership, and only live ones', async () => {
    await pinProjectForSession(PROJECT_ID);
    const lookup = statements.find((entry) => entry.sql.includes('SELECT p.tenant_id'));
    expect(lookup?.sql).toContain('FROM apiome.tenant_users WHERE user_id = $2::uuid');
    expect(lookup?.sql).toContain('p.deleted_at IS NULL');
    expect(lookup?.params).toEqual([PROJECT_ID, 'user-1']);
  });

  it('refuses at the limit without writing', async () => {
    script.count = 8;
    await expect(pinProjectForSession(PROJECT_ID)).resolves.toBe('limit_reached');
    expect(sqlRun().some((sql) => sql.includes('INSERT'))).toBe(false);
  });

  it('reports an existing pin as such, even at the limit', async () => {
    script.existing = true;
    script.count = 8;
    await expect(pinProjectForSession(PROJECT_ID)).resolves.toBe('already_pinned');
    expect(sqlRun().some((sql) => sql.includes('INSERT'))).toBe(false);
  });

  it('is not_found for a project the reader cannot reach', async () => {
    script.projectTenant = null;
    await expect(pinProjectForSession(PROJECT_ID)).resolves.toBe('not_found');
    expect(sqlRun().some((sql) => sql.includes('INSERT'))).toBe(false);
  });

  it.each(['', 'p-1', `${PROJECT_ID}' OR 1=1 --`])('refuses %p without a connection', async (id) => {
    await expect(pinProjectForSession(id)).resolves.toBe('not_found');
    expect(mockConnect).not.toHaveBeenCalled();
  });

  it('is an error without a signed-in reader', async () => {
    (getAuthSession as jest.Mock).mockResolvedValue(null);
    await expect(pinProjectForSession(PROJECT_ID)).resolves.toBe('error');
    expect(mockConnect).not.toHaveBeenCalled();
  });

  it('rolls back, releases and reports an error when a statement fails', async () => {
    script.failOn = 'INSERT INTO apiome.project_pins';
    await expect(pinProjectForSession(PROJECT_ID)).resolves.toBe('error');
    expect(sqlRun()).toContain('ROLLBACK');
    expect(release).toHaveBeenCalledTimes(1);
  });

  it('is an error when no connection can be had', async () => {
    mockConnect.mockRejectedValueOnce(new Error('pool exhausted'));
    await expect(pinProjectForSession(PROJECT_ID)).resolves.toBe('error');
  });
});

/* -------------------------------------------------------------------------
   unpinProjectForSession and listPinnedProjectIdsForSession
   ------------------------------------------------------------------------- */

describe('unpinProjectForSession', () => {
  it("deletes only the reader's own pin", async () => {
    await expect(unpinProjectForSession(PROJECT_ID)).resolves.toBe(true);
    expect(poolQueries[0].sql).toContain('DELETE FROM apiome.project_pins');
    expect(poolQueries[0].params).toEqual(['user-1', PROJECT_ID]);
  });

  it('refuses a malformed id and a signed-out reader without touching the database', async () => {
    await expect(unpinProjectForSession('nope')).resolves.toBe(false);
    (getAuthSession as jest.Mock).mockResolvedValue(null);
    await expect(unpinProjectForSession(PROJECT_ID)).resolves.toBe(false);
    expect(poolQueries).toHaveLength(0);
  });

  it('reports a failed write as false', async () => {
    mockPoolQuery.mockRejectedValueOnce(new Error('down'));
    await expect(unpinProjectForSession(PROJECT_ID)).resolves.toBe(false);
  });
});

describe('listPinnedProjectsForSession (#542)', () => {
  it('maps the shared statement rows to favorites', async () => {
    await expect(listPinnedProjectsForSession()).resolves.toEqual([
      { projectId: 'p-1', projectName: 'Orders', versionLabel: 'v1.0.0', pinnedAt: '2026-10-21T10:00:00.000Z' },
      { projectId: 'p-2', projectName: 'Billing', versionLabel: null, pinnedAt: '2026-10-20T10:00:00.000Z' },
    ]);
    expect(poolQueries[0].sql).toContain('FROM apiome.tenant_users WHERE user_id = $1');
  });

  it('is empty when signed out, without touching the database', async () => {
    (getAuthSession as jest.Mock).mockResolvedValue(null);
    await expect(listPinnedProjectsForSession()).resolves.toEqual([]);
    expect(poolQueries).toHaveLength(0);
  });
});

describe('listPinnedProjectIdsForSession', () => {
  it("lists the reader's live pins in the current workspace, newest first", async () => {
    await expect(listPinnedProjectIdsForSession()).resolves.toEqual(['p-1', 'p-2']);
    const [{ sql, params }] = poolQueries;
    expect(params).toEqual(['user-1', 'tenant-1', 8]);
    expect(sql).toContain('p.deleted_at IS NULL');
    expect(sql).toContain('ORDER BY pp.pinned_at DESC');
  });

  it('is empty with no current workspace, or when the read fails', async () => {
    (getAuthSession as jest.Mock).mockResolvedValue({ user: { user_id: 'user-1' } });
    await expect(listPinnedProjectIdsForSession()).resolves.toEqual([]);
    expect(poolQueries).toHaveLength(0);

    (getAuthSession as jest.Mock).mockResolvedValue({
      user: { user_id: 'user-1', current_tenant_id: 'tenant-1' },
    });
    mockPoolQuery.mockRejectedValueOnce(new Error('down'));
    await expect(listPinnedProjectIdsForSession()).resolves.toEqual([]);
  });
});

/* -------------------------------------------------------------------------
   pinToast
   ------------------------------------------------------------------------- */

describe('pinToast', () => {
  it.each([
    ['pinned', 'success', 'Pinned "Orders" to Home.'],
    ['already_pinned', 'success', 'Pinned "Orders" to Home.'],
    ['limit_reached', 'error', 'You can pin up to 8 projects. Unpin one on Home first.'],
    ['not_found', 'error', '"Orders" can no longer be pinned.'],
    ['error', 'error', 'Could not pin "Orders". Try again.'],
  ] as const)('words %s', (status, tone, message) => {
    expect(pinToast(status, 'Orders')).toEqual({ tone, message });
  });
});
