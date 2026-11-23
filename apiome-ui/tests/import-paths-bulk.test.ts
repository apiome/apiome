/**
 * @jest-environment node
 *
 * The paths-and-security import as set-based statements (DBP-1.9, #7192):
 * `lib/db/import-openapi-paths-security.ts`. The rows are built in memory, with ids assigned up
 * front, and each table is written by one statement whatever the specification's size.
 */

import { beforeEach, describe, expect, jest, test } from '@jest/globals';

const mockPool = {
  statements: [] as Array<{ sql: string; params: unknown[] }>,
  connects: 0,
  releases: 0,
  classes: [] as Array<{ id: string; name: string }>,
  failOn: null as string | null,
};

jest.mock('../lib/db/db', () => {
  const query = async (sql: string, params: unknown[] = []) => {
    mockPool.statements.push({ sql, params });
    if (mockPool.failOn && sql.includes(mockPool.failOn)) throw new Error('simulated failure');
    if (sql.includes('FROM apiome.classes')) return { rows: mockPool.classes, rowCount: mockPool.classes.length };
    return { rows: [], rowCount: 0 };
  };
  return {
    query,
    connect: async () => {
      mockPool.connects += 1;
      return { query, release: () => (mockPool.releases += 1) };
    },
  };
});

import {
  buildPathImportRows,
  CLASS_LOOKUP_SQL,
  importOpenAPIPathsAndSecurity,
} from '../lib/db/import-openapi-paths-security';
import type { ParsedPath, ParsedSecurityScheme } from '../src/app/utils/openapi-import';

/** Sequential ids, so a test can read parent links. */
function counter(): () => string {
  let n = 0;
  return () => `id-${(n += 1)}`;
}

/** `count` paths of four operations each. */
function manyPaths(count: number): ParsedPath[] {
  return Array.from({ length: count }, (_, i) => ({
    path: `/things${i}/{id}`,
    parameters: [{ name: 'id', in: 'path', required: true, schema: { type: 'string' } }],
    operations: ['GET', 'POST', 'PUT', 'DELETE'].map((method) => ({
      method,
      operationId: `${method.toLowerCase()}Thing${i}`,
      parameters: [{ name: 'verbose', in: 'query', schema: { type: 'boolean' } }],
      requestBody:
        method === 'POST' || method === 'PUT'
          ? { required: true, content: { 'application/json': { $ref: '#/components/schemas/Thing' } } }
          : undefined,
      responses: {
        '200': { description: 'OK', content: { 'application/json': { $ref: '#/components/schemas/Thing' } } },
        '404': { description: 'Not found' },
      },
    })),
  })) as unknown as ParsedPath[];
}

const SCHEMES = [
  { scheme_name: 'key', scheme_type: 'apiKey', in_location: 'header', param_name: 'X-Key' },
] as unknown as ParsedSecurityScheme[];

/** The table a recorded statement inserts into, or its first keyword. */
function target(sql: string): string {
  return /^INSERT INTO apiome\.(\w+)/.exec(sql)?.[1] ?? sql.trim().split(/\s+/)[0];
}

beforeEach(() => {
  mockPool.statements = [];
  mockPool.connects = 0;
  mockPool.releases = 0;
  mockPool.classes = [{ id: 'class-thing', name: 'Thing' }];
  mockPool.failOn = null;
});

describe('buildPathImportRows', () => {
  const classes = new Map([['Thing', 'class-thing']]);

  test('links children to parents through ids assigned up front', () => {
    const rows = buildPathImportRows('ver-1', manyPaths(1), classes, counter());
    const pathId = rows.version_path[0].id;
    expect(rows.version_path[0]).toMatchObject({ version_id: 'ver-1', pathname: '/things0/{id}', metadata: null });
    expect(rows.path_operation).toHaveLength(4);
    expect(rows.path_operation.every((op) => op.version_path_id === pathId)).toBe(true);
    const opIds = rows.path_operation.map((op) => op.id);
    expect(rows.path_operation_description.map((d) => d.path_operation_id)).toEqual(opIds);
    expect(rows.path_operation_request_body_link.map((l) => l.path_operation_id)).toEqual([opIds[1], opIds[2]]);
  });

  test('an operation parameter is stored once per path and linked from every operation', () => {
    const rows = buildPathImportRows('ver-1', manyPaths(1), classes, counter());
    expect(rows.shared_path_parameter.map((p) => `${p.name}:${p.in_location}`)).toEqual(['id:path', 'verbose:query']);
    const verbose = rows.shared_path_parameter[1].id;
    expect(rows.path_operation_parameter_link).toHaveLength(4);
    expect(rows.path_operation_parameter_link.every((l) => l.shared_path_parameter_id === verbose)).toBe(true);
  });

  test('an operation parameter that repeats a path parameter links to it', () => {
    const paths = [
      {
        path: '/a/{id}',
        parameters: [{ name: 'id', in: 'path', schema: { type: 'string' } }],
        operations: [{ method: 'GET', parameters: [{ name: 'id', in: 'path' }, { name: 'id', in: 'path' }], responses: {} }],
      },
    ] as unknown as ParsedPath[];
    const rows = buildPathImportRows('ver-1', paths, classes, counter());
    expect(rows.shared_path_parameter).toHaveLength(1);
    expect(rows.path_operation_parameter_link).toEqual([
      {
        path_operation_id: rows.path_operation[0].id,
        shared_path_parameter_id: rows.shared_path_parameter[0].id,
        metadata: null,
      },
    ]);
  });

  test('a path parameter declared twice keeps the first row and the later description and data', () => {
    const paths = [
      {
        path: '/a',
        parameters: [
          { name: 'q', in: 'query', description: 'first', schema: { type: 'string' } },
          { name: 'q', in: 'query', description: 'second', schema: { type: 'integer' }, required: true },
        ],
        operations: [],
      },
    ] as unknown as ParsedPath[];
    const rows = buildPathImportRows('ver-1', paths, classes, counter());
    expect(rows.shared_path_parameter).toHaveLength(1);
    expect(rows.shared_path_parameter[0]).toMatchObject({
      id: 'id-2',
      description: 'second',
      data: { type: 'integer', required: true },
    });
  });

  test('operations of a path share one response row per status code', () => {
    const rows = buildPathImportRows('ver-1', manyPaths(1), classes, counter());
    expect(rows.shared_path_response.map((r) => r.status_code)).toEqual(['200', '404']);
    expect(rows.path_operation_response_link).toHaveLength(8);
    expect(rows.shared_path_response_content).toHaveLength(1);
    expect(rows.shared_path_response[0]).toMatchObject({
      class_id: 'class-thing',
      inline_schema: null,
      schema_mode: 'class',
      data: null,
    });
    expect(rows.shared_path_response[1]).toMatchObject({ class_id: null, inline_schema: null, data: {} });
  });

  test('a later operation updates a shared response the way the upsert did', () => {
    const paths = [
      {
        path: '/a',
        operations: [
          {
            method: 'GET',
            responses: {
              '200': {
                description: 'first',
                headers: { 'X-Rate': { schema: { type: 'integer' } } },
                content: { 'application/json': { $ref: '#/components/schemas/Thing' } },
              },
            },
          },
          {
            method: 'POST',
            responses: {
              '200': {
                description: 'second',
                content: {
                  'application/json': { schema: { type: 'object' } },
                  'text/plain': { schema: { type: 'string' } },
                },
              },
            },
          },
        ],
      },
    ] as unknown as ParsedPath[];
    const rows = buildPathImportRows('ver-1', paths, classes, counter());
    expect(rows.shared_path_response).toHaveLength(1);
    const response = rows.shared_path_response[0];
    // The later description and schema mode win; data and class are kept when the later has none.
    expect(response.description).toBe('second');
    expect(response.data).toEqual({ headers: { 'X-Rate': { schema: { type: 'integer' } } } });
    expect(response.class_id).toBe('class-thing');
    expect(response.schema_mode).toBe('object');
    expect(response.inline_schema).not.toBeNull();
    // A media type is written once per response: the first definition stays.
    expect(rows.shared_path_response_content.map((c) => [c.media_type, c.class_id])).toEqual([
      ['application/json', 'class-thing'],
      ['text/plain', null],
    ]);
  });

  test('a $ref to a class the version does not have stays unresolved', () => {
    const rows = buildPathImportRows('ver-1', manyPaths(1), new Map(), counter());
    expect(rows.shared_path_response[0]).toMatchObject({ class_id: null, schema_mode: 'object' });
    // A request body media type with neither a class nor an inline schema is not written.
    expect(rows.shared_path_request_body_content).toHaveLength(0);
    expect(rows.shared_path_request_body).toHaveLength(2);
  });
});

describe('importOpenAPIPathsAndSecurity', () => {
  test('writes each table with one statement, parents before children', async () => {
    const result = await importOpenAPIPathsAndSecurity('ver-1', manyPaths(3), SCHEMES);
    expect(result).toEqual({ success: true });
    expect(mockPool.statements.map((s) => target(s.sql))).toEqual([
      'BEGIN',
      'version_security_scheme',
      'SELECT',
      'version_path',
      'shared_path_parameter',
      'path_operation',
      'path_operation_description',
      'path_operation_parameter_link',
      'shared_path_request_body',
      'shared_path_request_body_content',
      'path_operation_request_body_link',
      'shared_path_response',
      'shared_path_response_content',
      'path_operation_response_link',
      'COMMIT',
    ]);
  });

  test.each([1, 250])('the statement count does not depend on the size (%i paths)', async (count) => {
    await importOpenAPIPathsAndSecurity('ver-1', manyPaths(count), SCHEMES);
    expect(mockPool.statements).toHaveLength(15);
    const operations = mockPool.statements.find((s) => target(s.sql) === 'path_operation');
    expect(JSON.parse(String(operations?.params[0]))).toHaveLength(count * 4);
  });

  test('reads only live classes, so the partial index applies and a deleted class is not referenced', async () => {
    await importOpenAPIPathsAndSecurity('ver-1', manyPaths(1), []);
    expect(CLASS_LOOKUP_SQL).toContain('deleted_at IS NULL');
    expect(mockPool.statements.some((s) => s.sql === CLASS_LOOKUP_SQL)).toBe(true);
  });

  test('upserts security schemes in one statement, keeping the last definition of a name', async () => {
    const schemes = [
      { scheme_name: 'key', scheme_type: 'apiKey', in_location: 'header', param_name: 'X-Old' },
      { scheme_name: 'bearer', scheme_type: 'http', http_scheme: 'bearer', data: { bearerFormat: 'JWT' } },
      { scheme_name: 'key', scheme_type: 'apiKey', in_location: 'header', param_name: 'X-New' },
    ] as unknown as ParsedSecurityScheme[];
    await importOpenAPIPathsAndSecurity('ver-1', [], schemes);
    expect(mockPool.statements.map((s) => target(s.sql))).toEqual(['BEGIN', 'version_security_scheme', 'COMMIT']);
    const statement = mockPool.statements[1];
    expect(statement.sql).toContain('ON CONFLICT (version_id, scheme_name) DO UPDATE');
    expect(JSON.parse(String(statement.params[0]))).toEqual([
      expect.objectContaining({ scheme_name: 'key', param_name: 'X-New', data: {} }),
      expect.objectContaining({ scheme_name: 'bearer', data: { bearerFormat: 'JWT' } }),
    ]);
  });

  test('checks out one client and releases it', async () => {
    await importOpenAPIPathsAndSecurity('ver-1', manyPaths(1), SCHEMES);
    expect(mockPool.connects).toBe(1);
    expect(mockPool.releases).toBe(1);
  });

  test("runs on the caller's client when given one, and leaves it checked out", async () => {
    const statements: string[] = [];
    const client = {
      query: async (sql: string) => {
        statements.push(target(sql));
        return { rows: [], rowCount: 0 };
      },
      release: jest.fn(),
    };
    const result = await importOpenAPIPathsAndSecurity('ver-1', manyPaths(1), SCHEMES, client);
    expect(result).toEqual({ success: true });
    expect(mockPool.connects).toBe(0);
    expect(client.release).not.toHaveBeenCalled();
    expect(statements[0]).toBe('BEGIN');
    expect(statements[statements.length - 1]).toBe('COMMIT');
  });

  test('a failed statement rolls everything back and reports the error', async () => {
    mockPool.failOn = 'INSERT INTO apiome.path_operation ';
    const result = await importOpenAPIPathsAndSecurity('ver-1', manyPaths(1), SCHEMES);
    expect(result).toEqual({ success: false, error: 'simulated failure' });
    expect(target(mockPool.statements[mockPool.statements.length - 1].sql)).toBe('ROLLBACK');
    expect(mockPool.releases).toBe(1);
  });
});
