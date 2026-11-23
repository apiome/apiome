/**
 * @jest-environment node
 *
 * Set-based inserts for the import pipeline (DBP-1.9, #7192): `lib/db/import-bulk.ts`.
 */

import { describe, expect, jest, test } from '@jest/globals';

import { BULK_CHUNK_ROWS, bulkInsert, bulkInsertSql } from '../lib/db/import-bulk';

/** A client that records every statement and answers with `rows`. */
function recordingClient(rows: (params: unknown[]) => unknown[] = () => []) {
  const calls: Array<{ sql: string; params: unknown[] }> = [];
  const query = jest.fn(async (sql: string, params: unknown[] = []) => {
    calls.push({ sql, params });
    const returned = rows(params);
    return { rows: returned, rowCount: JSON.parse(String(params[0])).length };
  });
  return { calls, client: { query } as never };
}

describe('bulkInsertSql', () => {
  test('expands one JSON array into rows of the table type', () => {
    expect(bulkInsertSql('classes', ['id', 'version_id', 'name'])).toBe(
      'INSERT INTO apiome.classes (id, version_id, name) ' +
        'SELECT id, version_id, name FROM jsonb_populate_recordset(NULL::apiome.classes, $1::jsonb)',
    );
  });

  test('appends the conflict and returning clauses', () => {
    const sql = bulkInsertSql('properties', ['id', 'name'], {
      conflict: 'ON CONFLICT (project_id, name) DO NOTHING',
      returning: 'id',
    });
    expect(sql.endsWith(' ON CONFLICT (project_id, name) DO NOTHING RETURNING id')).toBe(true);
  });

  test.each([
    ['a table name with SQL in it', 'classes; DROP TABLE x', ['id']],
    ['a schema-qualified table', 'apiome.classes', ['id']],
    ['a column with SQL in it', 'classes', ['id', 'name) VALUES (1']],
    ['an upper-case identifier', 'Classes', ['id']],
  ])('rejects %s', (_label, table, columns) => {
    expect(() => bulkInsertSql(table, columns)).toThrow('is not a plain identifier');
  });

  test('rejects an empty column list', () => {
    expect(() => bulkInsertSql('classes', [])).toThrow('no columns');
  });
});

describe('bulkInsert', () => {
  test('sends nothing for no rows', async () => {
    const { client, calls } = recordingClient();
    expect(await bulkInsert(client, 'classes', ['id'], [])).toEqual({ rowCount: 0, rows: [] });
    expect(calls).toHaveLength(0);
  });

  test('sends every row of a table in one statement, JSON values unstringified', async () => {
    const { client, calls } = recordingClient();
    const rows = [
      { id: 'a', schema: { type: 'object' }, description: null },
      { id: 'b', schema: { type: 'string' }, description: 'B' },
    ];
    const result = await bulkInsert(client, 'classes', ['id', 'schema', 'description'], rows);
    expect(result.rowCount).toBe(2);
    expect(calls).toHaveLength(1);
    expect(JSON.parse(String(calls[0].params[0]))).toEqual(rows);
  });

  test('uses one statement per chunk and keeps row order', async () => {
    const { client, calls } = recordingClient();
    const rows = Array.from({ length: 7 }, (_, i) => ({ id: `r${i}` }));
    await bulkInsert(client, 'classes', ['id'], rows, { chunkRows: 3 });
    expect(calls.map((c) => JSON.parse(String(c.params[0])).map((r: { id: string }) => r.id))).toEqual([
      ['r0', 'r1', 'r2'],
      ['r3', 'r4', 'r5'],
      ['r6'],
    ]);
  });

  test('a default chunk holds thousands of rows, so a large import stays at a few statements', async () => {
    const { client, calls } = recordingClient();
    const rows = Array.from({ length: BULK_CHUNK_ROWS * 2 + 1 }, (_, i) => ({ id: `r${i}` }));
    await bulkInsert(client, 'class_properties', ['id'], rows);
    expect(calls).toHaveLength(3);
  });

  test('concatenates the RETURNING rows of every chunk', async () => {
    const { client } = recordingClient((params) =>
      JSON.parse(String(params[0])).map((r: { id: string }) => ({ id: r.id })),
    );
    const rows = Array.from({ length: 5 }, (_, i) => ({ id: `r${i}` }));
    const result = await bulkInsert(client, 'properties', ['id'], rows, { chunkRows: 2, returning: 'id' });
    expect(result.rows.map((r) => r.id)).toEqual(['r0', 'r1', 'r2', 'r3', 'r4']);
  });

  test('a failing statement rejects, so the caller can roll back', async () => {
    const client = { query: jest.fn(async () => Promise.reject(new Error('duplicate key'))) } as never;
    await expect(bulkInsert(client, 'classes', ['id'], [{ id: 'a' }])).rejects.toThrow('duplicate key');
  });
});
