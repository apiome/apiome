/**
 * Statement budgets for UI server actions (DBP-1.1, #7184).
 *
 * The real code runs against a scripted `pg` pool whose clients go through the same
 * `instrumentClient` wrapper `lib/db/db.ts` applies, so every statement is counted. Budgets are
 * recorded in `tests/query-budgets.json`; the DBP tickets that cut statements lower them.
 *
 * - `getClassesForVersion` — a guarded server action (`lib/db/helper-actions.ts`) with the real
 *   guard: the version's workspace, the caller's membership, then the read.
 * - `importOpenAPIPathsAndSecurity` — the paths-and-security step every OpenAPI import server
 *   action runs (DBP-1.9 replaces its per-row statements).
 * - `loadPathsForOpenAPIExport` — a version's paths for export and repository merges: six
 *   statements at 10 and at 1,000 operations (DBP-1.6, #7189).
 */

import fs from 'fs';
import path from 'path';
import YAML from 'yaml';
import { describe, test, expect, jest, beforeEach } from '@jest/globals';

/** The version the paths-export budget reads (DBP-1.6, #7189), answered by {@link exportAnswer}. */
let exportFixture: Record<string, Record<string, unknown>[]> | null = null;

/**
 * A version with `operations` operations (four per path: GET, POST, PUT, DELETE), each with a
 * description, a parameter and a response; every POST has a request body. Keyed by the
 * `PATHS_EXPORT_QUERIES` statement that returns each set of rows.
 */
function exportVersion(operations: number): Record<string, Record<string, unknown>[]> {
  const methods = ['GET', 'POST', 'PUT', 'DELETE'];
  const rows: Record<string, Record<string, unknown>[]> = {
    paths: [], operations: [], descriptions: [], parameters: [], requestBodies: [], responses: [],
  };
  for (let i = 0; i < operations; i += 1) {
    const pathId = `path-${String(Math.floor(i / methods.length)).padStart(4, '0')}`;
    if (i % methods.length === 0) {
      rows.paths.push({ id: pathId, pathname: `/r${pathId}`, summary: null, description: null });
    }
    const op = `op-${i}`;
    const method = methods[i % methods.length];
    rows.operations.push({ id: op, version_path_id: pathId, operation: method, metadata: null });
    rows.descriptions.push({ op_key: op, id: `d-${i}`, summary: `Op ${i}`, operation_id: `op${i}` });
    rows.parameters.push({ op_key: op, id: `pa-${i}`, name: 'id', in_location: 'path', data: { type: 'string' } });
    if (method === 'POST') {
      rows.requestBodies.push({
        op_key: op, id: `rb-${i}`, name: 'body', required: true,
        content_types: [{ id: `rbc-${i}`, media_type: 'application/json', inline_schema: { type: 'object' } }],
      });
    }
    rows.responses.push({
      op_key: op, id: `r-${i}`, status_code: '200', description: 'OK',
      content_types: [{ id: `rc-${i}`, media_type: 'application/json', class_name: 'Thing', class_id: 'c-1' }],
    });
  }
  return rows;
}

/** The fixture's rows for one of the paths-export statements, or `null` for any other statement. */
function exportAnswer(text: string): Record<string, unknown>[] | null {
  if (!exportFixture) return null;
  const key = (Object.keys(PATHS_EXPORT_QUERIES) as Array<keyof typeof PATHS_EXPORT_QUERIES>).find(
    (name) => PATHS_EXPORT_QUERIES[name] === text,
  );
  return key ? exportFixture[key] : null;
}

/** Answers every statement: no classes, one generated id per insert. */
function answer(sql: unknown): { rows: Record<string, unknown>[]; rowCount: number } {
  const text = String(sql);
  const exported = exportAnswer(text);
  if (exported) return { rows: exported, rowCount: exported.length };
  if (text.includes('UNION ALL')) return { rows: [{ '?column?': 1 }], rowCount: 1 };
  if (text.includes('FROM apiome.classes')) return { rows: [], rowCount: 0 };
  if (text.includes('tenant_id'))
    return { rows: [{ tenant_id: 'tenant-1', project_id: 'proj-1', found: 1 }], rowCount: 1 };
  return { rows: [{ id: `id-${Math.random().toString(36).slice(2)}` }], rowCount: 1 };
}

jest.mock('../lib/db/db', () => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { instrumentClient } = require('../lib/db/statement-stats');
  const makeClient = () =>
    instrumentClient({
      query: async (sql: unknown) =>
        answer(typeof sql === 'object' && sql ? (sql as { text: string }).text : sql),
      release: () => undefined,
    });
  const pool = makeClient() as Record<string, unknown>;
  pool.connect = async () => makeClient();
  return pool;
});
jest.mock('../lib/rest-auth', () => ({
  REST_API_BASE_URL: 'http://rest.test/v1',
  createRestAuthHeaders: jest.fn(() => ({ Authorization: 'Bearer test' })),
}));
jest.mock('next/headers', () => ({ cookies: jest.fn() }));
jest.mock('../lib/auth/admin-session', () => ({ verifyAdminSessionToken: jest.fn() }));

import * as sessionModule from '../lib/auth/server-session';
import { getClassesForVersion } from '../lib/db/helper-actions';
import { loadPathsForOpenAPIExport, PATHS_EXPORT_QUERIES } from '../lib/db/helper-paths-export';
import { importOpenAPIPathsAndSecurity } from '../lib/db/import-openapi-paths-security';
import {
  assertMaxQueries,
  captureStatements,
  QueryBudgetExceededError,
} from '../lib/db/statement-stats';
import { extractPaths, extractSecuritySchemes } from '../src/app/utils/openapi-import';

const session = sessionModule as unknown as { getAuthSession: jest.Mock };
const BUDGETS: Record<string, number> = JSON.parse(
  fs.readFileSync(path.join(__dirname, 'query-budgets.json'), 'utf-8'),
).budgets;
const SPEC = YAML.parse(
  fs.readFileSync(
    path.join(__dirname, 'fixtures/openapi32-operations/query-and-additional.yaml'),
    'utf-8',
  ),
);
const VERSION_ID = '00000000-0000-4000-8000-000000000123';

beforeEach(() => {
  session.getAuthSession.mockResolvedValue({
    user: { user_id: 'user-1', current_tenant_id: 'tenant-1' },
  } as never);
});

describe('server action statement budgets', () => {
  test('getClassesForVersion stays within its budget', async () => {
    const label = 'getClassesForVersion server action';
    const result = await assertMaxQueries(BUDGETS[label], label, () =>
      getClassesForVersion(VERSION_ID),
    );
    expect(JSON.parse(String(result))).toEqual([]);
  });

  test('the OpenAPI paths-and-security import stays within its budget', async () => {
    const label = 'importOpenAPIPathsAndSecurity (query-and-additional.yaml)';
    const result = await assertMaxQueries(BUDGETS[label], label, () =>
      importOpenAPIPathsAndSecurity(VERSION_ID, extractPaths(SPEC), extractSecuritySchemes(SPEC)),
    );
    expect(result).toEqual({ success: true });
  });

  test.each([10, 1000])(
    'the paths export reads %i operations in a constant number of statements',
    async (operations) => {
      const label = `loadPathsForOpenAPIExport (${operations.toLocaleString('en-US')} operations)`;
      exportFixture = exportVersion(operations);
      try {
        const result = JSON.parse(
          await assertMaxQueries(BUDGETS[label], label, () => loadPathsForOpenAPIExport(VERSION_ID)),
        );
        expect(result.success).toBe(true);
        const ops = result.paths.flatMap((p: { operations: unknown[] }) => p.operations);
        expect(ops).toHaveLength(operations);
        expect(result.paths[0].operations.map((o: { operation: string }) => o.operation)).toEqual([
          'GET', 'POST', 'PUT', 'DELETE',
        ]);
        expect(result.paths[0].operations[1].requestBody.content_types[0].media_type).toBe('application/json');
        expect(result.paths[0].operations[0].requestBody).toBeNull();
      } finally {
        exportFixture = null;
      }
    },
  );

  test('exceeding a recorded budget fails and names the statements', async () => {
    const label = 'getClassesForVersion server action';
    const run = assertMaxQueries(BUDGETS[label] - 1, label, () => getClassesForVersion(VERSION_ID));
    await expect(run).rejects.toBeInstanceOf(QueryBudgetExceededError);
  });

  test('the recorded budgets are the measured counts (lower them when a change cuts statements)', async () => {
    const classes = await captureStatements(() => getClassesForVersion(VERSION_ID));
    const imported = await captureStatements(() =>
      importOpenAPIPathsAndSecurity(VERSION_ID, extractPaths(SPEC), extractSecuritySchemes(SPEC)),
    );
    const exported: Record<string, number> = {};
    for (const operations of [10, 1000]) {
      exportFixture = exportVersion(operations);
      try {
        const { stats } = await captureStatements(() => loadPathsForOpenAPIExport(VERSION_ID));
        exported[`loadPathsForOpenAPIExport (${operations.toLocaleString('en-US')} operations)`] = stats.count;
      } finally {
        exportFixture = null;
      }
    }
    expect({
      'getClassesForVersion server action': classes.stats.count,
      'importOpenAPIPathsAndSecurity (query-and-additional.yaml)': imported.stats.count,
      ...exported,
    }).toEqual(BUDGETS);
  });
});
