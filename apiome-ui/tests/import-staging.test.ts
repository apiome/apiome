/**
 * @jest-environment node
 *
 * Staged imports (DBP-1.9, #7192): `lib/db/import-staging.ts`. An import awaiting approval is
 * committed but hidden; these tests pin what Accept, Reject and the sweeper send to the database.
 * `tests/import-staging-db.test.ts` runs the same paths against a real PostgreSQL.
 */

import { afterEach, beforeEach, describe, expect, jest, test } from '@jest/globals';

const mockDb = {
  statements: [] as Array<{ sql: string; params: unknown[] }>,
  /** The staged version the lock query finds, or `null` when nothing is staged. */
  staged: null as null | { project_id: string; import_pending: unknown },
  /** Versions the sweeper's lookup returns. */
  due: [] as string[],
  /** Version ids whose discard fails. */
  failFor: new Set<string>(),
  /** Whether the plan probe finds the user at the limit. */
  atLimit: false,
  connects: 0,
  releases: 0,
};

jest.mock('../lib/db/db', () => {
  const query = async (sql: string, params: unknown[] = []) => {
    mockDb.statements.push({ sql, params });
    if (sql.includes('FOR UPDATE')) {
      if (mockDb.failFor.has(String(params[0]))) throw new Error('lock failed');
      return { rows: mockDb.staged ? [mockDb.staged] : [], rowCount: mockDb.staged ? 1 : 0 };
    }
    if (sql.includes('make_interval')) return { rows: mockDb.due.map((id) => ({ id })), rowCount: mockDb.due.length };
    if (sql.includes('FROM apiome.user_entitlements')) {
      return { rowCount: 1, rows: [{ plan_code: 'free', max_tenants: 1, max_projects: 1, max_versions: 3 }] };
    }
    if (sql.includes('OFFSET $2 LIMIT 1')) return { rows: mockDb.atLimit ? [{ '?column?': 1 }] : [], rowCount: 0 };
    return { rows: [], rowCount: 0 };
  };
  return {
    query,
    connect: async () => {
      mockDb.connects += 1;
      return { query, release: () => (mockDb.releases += 1) };
    },
  };
});

import {
  acceptStagedImportTx,
  DEFAULT_IMPORT_PENDING_TTL_MINUTES,
  discardStagedImport,
  discardStagedImportTx,
  importPendingTtlMs,
  listRepositorySourcesTx,
  STAGED_IMPORT_GONE_MESSAGE,
  startImportStagingSweeper,
  sweepAbandonedImports,
  writeStagedManifestTx,
  type StagedImportManifest,
} from '../lib/db/import-staging';

// eslint-disable-next-line @typescript-eslint/no-require-imports
const pool = require('../lib/db/db');

const MANIFEST: StagedImportManifest = {
  jobId: 'job-1',
  projectCreated: false,
  propertyIds: ['prop-1', 'prop-2'],
  sourcesCreated: [],
  sourcesTouched: [],
};

/** One-line SQL of each recorded statement. */
function sqls(): string[] {
  return mockDb.statements.map((s) => s.sql.split(/\s+/).filter(Boolean).join(' '));
}

beforeEach(() => {
  mockDb.statements = [];
  mockDb.staged = { project_id: 'proj-1', import_pending: MANIFEST };
  mockDb.due = [];
  mockDb.failFor = new Set();
  mockDb.atLimit = false;
  mockDb.connects = 0;
  mockDb.releases = 0;
});

describe('importPendingTtlMs', () => {
  const saved = process.env.IMPORT_PENDING_TTL_MINUTES;
  afterEach(() => {
    if (saved === undefined) delete process.env.IMPORT_PENDING_TTL_MINUTES;
    else process.env.IMPORT_PENDING_TTL_MINUTES = saved;
  });

  test('defaults to an hour', () => {
    delete process.env.IMPORT_PENDING_TTL_MINUTES;
    expect(DEFAULT_IMPORT_PENDING_TTL_MINUTES).toBe(60);
    expect(importPendingTtlMs()).toBe(3_600_000);
  });

  test('reads IMPORT_PENDING_TTL_MINUTES', () => {
    process.env.IMPORT_PENDING_TTL_MINUTES = '15';
    expect(importPendingTtlMs()).toBe(900_000);
  });

  test.each(['0', '-5', 'soon', ''])('falls back to the default for %p', (value) => {
    process.env.IMPORT_PENDING_TTL_MINUTES = value;
    expect(importPendingTtlMs()).toBe(3_600_000);
  });
});

describe('writeStagedManifestTx', () => {
  test('stores the manifest on the staged version only', async () => {
    await writeStagedManifestTx(pool, 'ver-1', MANIFEST);
    expect(sqls()[0]).toBe(
      'UPDATE apiome.versions SET import_pending = $2::jsonb WHERE id = $1 AND import_pending_at IS NOT NULL',
    );
    expect(mockDb.statements[0].params).toEqual(['ver-1', JSON.stringify(MANIFEST)]);
  });
});

describe('listRepositorySourcesTx', () => {
  test("reads the project's source rows", async () => {
    await listRepositorySourcesTx(pool, 'proj-1');
    expect(sqls()[0]).toContain('FROM apiome.project_repository_sources WHERE project_id = $1');
  });
});

describe('acceptStagedImportTx', () => {
  test('locks the staged version, then makes it visible', async () => {
    const result = await acceptStagedImportTx(pool, 'ver-1', 'user-1');
    expect(result).toEqual({ ok: true, projectId: 'proj-1', projectCreated: false });
    const run = sqls();
    expect(run[0]).toContain('WHERE id = $1 AND import_pending_at IS NOT NULL FOR UPDATE');
    expect(run[0]).not.toContain('SKIP LOCKED');
    expect(run[run.length - 1]).toBe(
      'UPDATE apiome.versions SET deleted_at = NULL, import_pending_at = NULL, import_pending = NULL WHERE id = $1',
    );
    expect(run.some((sql) => sql.startsWith('UPDATE apiome.projects'))).toBe(false);
  });

  test('also makes the project visible when the import created it', async () => {
    mockDb.staged = { project_id: 'proj-9', import_pending: { ...MANIFEST, projectCreated: true } };
    const result = await acceptStagedImportTx(pool, 'ver-1', 'user-1');
    expect(result).toEqual({ ok: true, projectId: 'proj-9', projectCreated: true });
    const last = mockDb.statements[mockDb.statements.length - 1];
    expect(last.sql).toContain('UPDATE apiome.projects SET deleted_at = NULL WHERE id = $1 AND deleted_at IS NOT NULL');
    expect(last.params).toEqual(['proj-9']);
  });

  test('changes nothing when the import is no longer staged', async () => {
    mockDb.staged = null;
    const result = await acceptStagedImportTx(pool, 'ver-1', 'user-1');
    expect(result).toEqual({ ok: false, error: STAGED_IMPORT_GONE_MESSAGE });
    expect(mockDb.statements).toHaveLength(1);
  });

  test('checks the plan again, since a staged version did not count toward it', async () => {
    mockDb.atLimit = true;
    const result = await acceptStagedImportTx(pool, 'ver-1', 'user-1');
    expect(result.ok).toBe(false);
    expect(!result.ok && result.error).toContain('3 version');
    expect(sqls().some((sql) => sql.startsWith('UPDATE'))).toBe(false);
  });

  test('checks the project limit too when the import created the project', async () => {
    mockDb.staged = { project_id: 'proj-9', import_pending: { ...MANIFEST, projectCreated: true } };
    mockDb.atLimit = true;
    const result = await acceptStagedImportTx(pool, 'ver-1', 'user-1');
    expect(!result.ok && result.error).toContain('1 project');
  });

  test('reads a manifest pg returned as text', async () => {
    mockDb.staged = { project_id: 'proj-9', import_pending: JSON.stringify({ ...MANIFEST, projectCreated: true }) };
    expect(await acceptStagedImportTx(pool, 'ver-1', 'user-1')).toMatchObject({ ok: true, projectCreated: true });
  });
});

describe('discardStagedImportTx', () => {
  test('deletes the version and the library properties the import added', async () => {
    expect(await discardStagedImportTx(pool, 'ver-1')).toBe(true);
    const run = sqls();
    expect(run.slice(1, 4)).toEqual([
      'DELETE FROM apiome.version_path WHERE version_id = $1',
      'DELETE FROM apiome.classes WHERE version_id = $1',
      'DELETE FROM apiome.versions WHERE id = $1',
    ]);
    const properties = mockDb.statements[4];
    expect(properties.sql).toContain('DELETE FROM apiome.properties p');
    expect(properties.params).toEqual([['prop-1', 'prop-2']]);
    // A property something else has started to use is kept.
    expect(properties.sql).toContain('NOT EXISTS (SELECT 1 FROM apiome.class_properties cp WHERE cp.property_id = p.id)');
    expect(run.some((sql) => sql.startsWith('DELETE FROM apiome.projects'))).toBe(false);
  });

  test('deletes the project too when the import created it and it is still staged', async () => {
    mockDb.staged = { project_id: 'proj-9', import_pending: { ...MANIFEST, projectCreated: true } };
    await discardStagedImportTx(pool, 'ver-1');
    const run = sqls();
    const project = run[run.length - 1];
    expect(project).toContain('DELETE FROM apiome.projects WHERE id = $1');
    expect(project).toContain('p.deleted_at IS NOT NULL');
    expect(project).toContain('NOT EXISTS (SELECT 1 FROM apiome.versions v WHERE v.project_id = $1)');
    expect(run[run.length - 2]).toContain('DELETE FROM apiome.properties WHERE project_id = $1');
  });

  test('puts repository source rows back as they were', async () => {
    const touched = [{ id: 'src-1', last_version_id: 'ver-0', last_blob_sha: 'abc', updated_at: '2026-11-01 00:00:00+00' }];
    mockDb.staged = {
      project_id: 'proj-1',
      import_pending: { ...MANIFEST, propertyIds: [], sourcesCreated: ['src-2'], sourcesTouched: touched },
    };
    await discardStagedImportTx(pool, 'ver-1');
    const restore = mockDb.statements.find((s) => s.sql.includes('UPDATE apiome.project_repository_sources'));
    expect(restore?.params).toEqual([JSON.stringify(touched)]);
    const removed = mockDb.statements.find((s) => s.sql.includes('DELETE FROM apiome.project_repository_sources'));
    expect(removed?.params).toEqual([['src-2']]);
    // Before the version goes: the foreign keys would otherwise null the columns being restored.
    const order = sqls();
    expect(order.findIndex((sql) => sql.includes('project_repository_sources'))).toBeLessThan(
      order.indexOf('DELETE FROM apiome.versions WHERE id = $1'),
    );
  });

  test('does nothing when the version is not staged', async () => {
    mockDb.staged = null;
    expect(await discardStagedImportTx(pool, 'ver-1')).toBe(false);
    expect(mockDb.statements).toHaveLength(1);
  });

  test('skips a version another session holds when asked to', async () => {
    await discardStagedImportTx(pool, 'ver-1', { skipLocked: true });
    expect(sqls()[0]).toContain('FOR UPDATE SKIP LOCKED');
  });

  test('tolerates a version staged without a manifest', async () => {
    mockDb.staged = { project_id: 'proj-1', import_pending: null };
    expect(await discardStagedImportTx(pool, 'ver-1')).toBe(true);
    expect(sqls().some((sql) => sql.includes('apiome.properties'))).toBe(false);
  });
});

describe('discardStagedImport', () => {
  test('runs in one transaction on its own client and releases it', async () => {
    expect(await discardStagedImport('ver-1')).toBe(true);
    const run = sqls();
    expect(run[0]).toBe('BEGIN');
    expect(run[run.length - 1]).toBe('COMMIT');
    expect([mockDb.connects, mockDb.releases]).toEqual([1, 1]);
  });

  test('rolls back and releases the client when a statement fails', async () => {
    mockDb.failFor.add('ver-1');
    await expect(discardStagedImport('ver-1')).rejects.toThrow('lock failed');
    expect(sqls()[sqls().length - 1]).toBe('ROLLBACK');
    expect([mockDb.connects, mockDb.releases]).toEqual([1, 1]);
  });
});

describe('sweepAbandonedImports', () => {
  test('discards the staged imports older than the time-to-live', async () => {
    mockDb.due = ['ver-1', 'ver-2'];
    expect(await sweepAbandonedImports({ ttlMs: 120_000 })).toBe(2);
    const lookup = mockDb.statements[0];
    expect(lookup.sql).toContain('import_pending_at IS NOT NULL');
    expect(lookup.sql).toContain('import_pending_at <= CURRENT_TIMESTAMP - make_interval(secs => $1)');
    expect(lookup.params).toEqual([120]);
    // Each in its own transaction, skipping a version an Accept or Reject is deciding on.
    expect(sqls().filter((sql) => sql === 'BEGIN')).toHaveLength(2);
    expect(sqls().filter((sql) => sql.includes('SKIP LOCKED'))).toHaveLength(2);
    expect(mockDb.releases).toBe(2);
  });

  test('uses IMPORT_PENDING_TTL_MINUTES when no time-to-live is given', async () => {
    await sweepAbandonedImports();
    expect(mockDb.statements[0].params).toEqual([importPendingTtlMs() / 1000]);
  });

  test('does not count a version it could not lock', async () => {
    mockDb.due = ['ver-1'];
    mockDb.staged = null;
    expect(await sweepAbandonedImports({ ttlMs: 0 })).toBe(0);
  });

  test('one failure does not stop the pass', async () => {
    mockDb.due = ['ver-bad', 'ver-2'];
    mockDb.failFor.add('ver-bad');
    const logged = jest.spyOn(console, 'error').mockImplementation(() => undefined);
    try {
      expect(await sweepAbandonedImports({ ttlMs: 0 })).toBe(1);
      expect(logged).toHaveBeenCalledTimes(1);
      expect(String(logged.mock.calls[0][0])).toContain('ver-bad');
    } finally {
      logged.mockRestore();
    }
  });
});

describe('startImportStagingSweeper', () => {
  const SWEEPER = Symbol.for('apiome.importStagingSweeper');
  const holder = globalThis as unknown as Record<symbol, ReturnType<typeof setInterval> | undefined>;

  afterEach(() => {
    if (holder[SWEEPER]) clearInterval(holder[SWEEPER]);
    delete holder[SWEEPER];
    jest.useRealTimers();
  });

  test('sweeps at once and then every quarter of the time-to-live, started once per process', async () => {
    jest.useFakeTimers();
    const interval = startImportStagingSweeper();
    expect(interval).toBe(15 * 60_000);
    expect(startImportStagingSweeper()).toBe(interval);
    await Promise.resolve();
    const lookups = () => mockDb.statements.filter((s) => s.sql.includes('make_interval')).length;
    expect(lookups()).toBe(1);
    jest.advanceTimersByTime(interval);
    await Promise.resolve();
    expect(lookups()).toBe(2);
  });

  test('a failed pass is logged, not thrown', async () => {
    const logged = jest.spyOn(console, 'error').mockImplementation(() => undefined);
    const original = pool.query;
    pool.query = async () => Promise.reject(new Error('database is down'));
    try {
      startImportStagingSweeper();
      await new Promise((resolve) => setImmediate(resolve));
      expect(String(logged.mock.calls[0]?.[0])).toContain('staged import sweep failed');
    } finally {
      pool.query = original;
      logged.mockRestore();
    }
  });
});
