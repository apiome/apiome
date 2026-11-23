/**
 * @jest-environment node
 *
 * The import pipeline's acceptance budget (DBP-1.9, #7192).
 *
 * The real importer, job runner, transaction helpers and staging store run against a scripted
 * `pg` pool whose clients go through `instrumentClient`, as `lib/db/db.ts` does, so every
 * statement is counted and every checkout is tracked:
 *
 * - a 1,000-operation, 2,000-class specification is staged and accepted in fewer than 100
 *   statements — one more than a 10-operation one, for its second 5,000-row chunk of properties;
 * - no pooled client is checked out while the job is `pending-approval`;
 * - Reject and Accept each take one client and give it back.
 *
 * The measured counts are recorded under `importBudgets` in `tests/query-budgets.json`.
 */

import fs from 'fs';
import path from 'path';
import { beforeEach, describe, expect, jest, test } from '@jest/globals';

const mockPool = {
  /** Clients checked out and not yet released. */
  checkedOut: 0,
  /** The most clients checked out at once. */
  peak: 0,
  /** Rows sent to each table by a bulk insert. */
  inserted: {} as Record<string, number>,
  /** The staged version's manifest, as the staging transaction wrote it. */
  manifest: null as unknown,
  /** Whether the staged version is still staged. */
  staged: false,
};

jest.mock('../lib/db/db', () => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { instrumentClient } = require('../lib/db/statement-stats');
  const answer = (text: string, params: unknown[]) => {
    const bulk = /^INSERT INTO apiome\.(\w+) .*jsonb_populate_recordset/.exec(text);
    if (bulk) {
      const rows = JSON.parse(String(params[0])) as Array<{ id?: string }>;
      mockPool.inserted[bulk[1]] = (mockPool.inserted[bulk[1]] ?? 0) + rows.length;
      return { rows: text.includes('RETURNING id') ? rows.map((r) => ({ id: r.id })) : [], rowCount: rows.length };
    }
    if (text.includes('INSERT INTO apiome.projects')) return { rows: [{ id: 'proj-1' }], rowCount: 1 };
    if (text.includes('INSERT INTO apiome.versions')) {
      mockPool.staged = params[6] === true;
      return { rows: [{ id: 'ver-1' }], rowCount: 1 };
    }
    if (text.includes('SET import_pending = $2::jsonb')) {
      mockPool.manifest = JSON.parse(String(params[1]));
      return { rows: [], rowCount: 1 };
    }
    if (text.includes('FOR UPDATE')) {
      const rows = mockPool.staged ? [{ project_id: 'proj-1', import_pending: mockPool.manifest }] : [];
      return { rows, rowCount: rows.length };
    }
    if (text.includes('SET deleted_at = NULL, import_pending_at = NULL') || text.startsWith('DELETE FROM apiome.versions')) {
      mockPool.staged = false;
    }
    return { rows: [], rowCount: 0 };
  };
  const makeClient = () =>
    instrumentClient({
      query: async (sql: unknown, params: unknown[] = []) => answer(String(sql), params),
      release: () => {
        mockPool.checkedOut -= 1;
      },
    });
  const pool = makeClient() as Record<string, unknown>;
  pool.connect = async () => {
    mockPool.checkedOut += 1;
    mockPool.peak = Math.max(mockPool.peak, mockPool.checkedOut);
    return makeClient();
  };
  return pool;
});
jest.mock('../lib/db/helper', () => ({
  permanentDeleteProject: jest.fn(),
  getTenantById: jest.fn(),
}));

import { commitImport, getImportStatus, rollbackImport, startImport } from '../lib/db/import-helper';
import { captureStatements } from '../lib/db/statement-stats';

const BUDGETS: Record<string, number> = JSON.parse(
  fs.readFileSync(path.join(__dirname, 'query-budgets.json'), 'utf-8'),
).importBudgets;

/** The acceptance criterion's ceiling for a 1,000-operation, 2,000-class specification. */
const MAX_STATEMENTS = 100;

/** An OpenAPI document with `operations` operations (four per path) and `classes` schemas. */
function specification(operations: number, classes: number): Record<string, unknown> {
  const schemas: Record<string, unknown> = {};
  for (let i = 0; i < classes; i += 1) {
    schemas[`Thing${i}`] = {
      type: 'object',
      properties: {
        id: { type: 'string', format: 'uuid' },
        name: { type: 'string', maxLength: 100 + (i % 7) },
        count: { type: 'integer' },
        tags: { type: 'array', items: { type: 'string' } },
        next: { $ref: `#/components/schemas/Thing${(i + 1) % classes}` },
      },
    };
  }
  const paths: Record<string, Record<string, unknown>> = {};
  const methods = ['get', 'post', 'put', 'delete'];
  for (let i = 0; i < operations; i += 1) {
    const pathname = `/things${Math.floor(i / 4)}/{id}`;
    const method = methods[i % 4];
    paths[pathname] ??= { parameters: [{ name: 'id', in: 'path', required: true, schema: { type: 'string' } }] };
    const ref = { $ref: `#/components/schemas/Thing${i % classes}` };
    paths[pathname][method] = {
      operationId: `${method}Thing${i}`,
      parameters: [{ name: 'verbose', in: 'query', schema: { type: 'boolean' } }],
      ...(method === 'post' || method === 'put'
        ? { requestBody: { required: true, content: { 'application/json': { schema: ref } } } }
        : {}),
      responses: {
        '200': { description: 'OK', content: { 'application/json': { schema: ref } } },
        '404': { description: 'Not found' },
      },
    };
  }
  return {
    openapi: '3.1.0',
    info: { title: 'Budget', version: '1.0.0' },
    paths,
    components: { schemas, securitySchemes: { key: { type: 'apiKey', in: 'header', name: 'X-Key' } } },
  };
}

/** Start an import of `document` and wait until it stops running. */
async function stage(document: Record<string, unknown>) {
  const schemas = Object.keys((document.components as { schemas: object }).schemas);
  const { jobId } = await startImport({
    tenantId: 'tenant-1',
    userId: 'user-1',
    sourceKind: 'openapi',
    document,
    project: { name: 'Budget', slug: 'budget' },
    version: { versionId: '1.0.0' },
    options: { selectedSchemas: schemas },
  } as never);
  for (;;) {
    const status = await getImportStatus(jobId);
    if (status.state !== 'queued' && status.state !== 'running') return { jobId, status };
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
}

beforeEach(() => {
  mockPool.checkedOut = 0;
  mockPool.peak = 0;
  mockPool.inserted = {};
  mockPool.manifest = null;
  mockPool.staged = false;
  jest.spyOn(console, 'error').mockImplementation(() => undefined);
});

describe('import pipeline statement budget (DBP-1.9)', () => {
  test('a 1,000-operation, 2,000-class specification is imported in fewer than 100 statements', async () => {
    const staged = await captureStatements(() => stage(specification(1000, 2000)));
    const { jobId, status } = staged.result;
    expect(status.state).toBe('pending-approval');
    expect(mockPool.inserted).toMatchObject({
      classes: 2000,
      class_properties: 10000,
      version_path: 250,
      path_operation: 1000,
      path_operation_response_link: 2000,
    });

    const accepted = await captureStatements(() => commitImport(jobId));
    expect(accepted.result).toEqual({ success: true });
    expect((await getImportStatus(jobId)).state).toBe('completed');

    const total = staged.stats.count + accepted.stats.count;
    expect(total).toBeLessThan(MAX_STATEMENTS);
    expect({ stage: staged.stats.count, accept: accepted.stats.count }).toEqual({
      stage: BUDGETS['stage (1,000 operations, 2,000 classes)'],
      accept: BUDGETS['accept'],
    });
  }, 60_000);

  test('a specification a hundred times smaller takes one statement fewer', async () => {
    const small = await captureStatements(() => stage(specification(10, 20)));
    expect(small.result.status.state).toBe('pending-approval');
    expect(small.stats.count).toBe(BUDGETS['stage (10 operations, 20 classes)']);
    // The only difference: 10,000 class properties are two 5,000-row statements.
    expect(BUDGETS['stage (1,000 operations, 2,000 classes)'] - small.stats.count).toBe(1);
  });

  test('no pooled client is held while the job is pending-approval', async () => {
    const { jobId, status } = await stage(specification(100, 50));
    expect(status.state).toBe('pending-approval');
    expect(status.transactionPending).toBe(true);
    // Every client the import took is back in the pool: all of them are idle.
    expect(mockPool.checkedOut).toBe(0);
    // And it only ever took one (one client per import job).
    expect(mockPool.peak).toBe(1);

    await commitImport(jobId);
    expect(mockPool.checkedOut).toBe(0);
    expect(mockPool.peak).toBe(1);
  });

  test('ten imports can await approval at once on a pool of ten', async () => {
    const jobs = [];
    for (let i = 0; i < 10; i += 1) jobs.push(await stage(specification(4, 2)));
    expect(jobs.every((job) => job.status.state === 'pending-approval')).toBe(true);
    expect(mockPool.checkedOut).toBe(0);
  });

  test('the staged import records what Reject must undo', async () => {
    await stage(specification(4, 3));
    expect(mockPool.manifest).toMatchObject({ projectCreated: true, sourcesCreated: [], sourcesTouched: [] });
    const manifest = mockPool.manifest as { jobId: string; propertyIds: string[] };
    expect(manifest.jobId).toEqual(expect.any(String));
    expect(manifest.propertyIds).toHaveLength(mockPool.inserted.properties);
  });

  test('Reject deletes the staged import within its budget and holds no client afterwards', async () => {
    const { jobId } = await stage(specification(1000, 2000));
    const rejected = await captureStatements(() => rollbackImport(jobId));
    expect(rejected.result).toEqual({ success: true });
    expect(rejected.stats.count).toBe(BUDGETS['reject']);
    const status = await getImportStatus(jobId);
    expect(status.state).toBe('rolled-back');
    expect(status.transactionPending).toBe(false);
    expect(mockPool.staged).toBe(false);
    expect(mockPool.checkedOut).toBe(0);
  }, 60_000);

  test('Accept after the staged import was swept fails cleanly and changes nothing', async () => {
    const { jobId } = await stage(specification(4, 2));
    mockPool.staged = false; // the sweeper discarded it (time-to-live passed, or the server restarted)
    const result = await commitImport(jobId);
    expect(result.success).toBe(false);
    expect(result.error).toContain('no longer awaiting approval');
    expect((await getImportStatus(jobId)).state).toBe('failed');
    expect(mockPool.checkedOut).toBe(0);
  });

  test('a second Accept or Reject of a decided import does nothing', async () => {
    const { jobId } = await stage(specification(4, 2));
    await commitImport(jobId);
    const again = await captureStatements(() => commitImport(jobId));
    expect(again.result.success).toBe(false);
    const reject = await captureStatements(() => rollbackImport(jobId));
    expect(reject.result).toEqual({ success: true });
    expect(again.stats.count + reject.stats.count).toBe(0);
  });
});
