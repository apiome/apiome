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
 */

import fs from 'fs';
import path from 'path';
import YAML from 'yaml';
import { describe, test, expect, jest, beforeEach } from '@jest/globals';

/** Answers every statement: no classes, one generated id per insert. */
function answer(sql: unknown): { rows: Record<string, unknown>[]; rowCount: number } {
  const text = String(sql);
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
    expect({
      'getClassesForVersion server action': classes.stats.count,
      'importOpenAPIPathsAndSecurity (query-and-additional.yaml)': imported.stats.count,
    }).toEqual(BUDGETS);
  });
});
