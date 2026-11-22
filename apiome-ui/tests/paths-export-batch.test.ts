/**
 * Set-based reads for the paths export, referenced classes and feature entitlements
 * (DBP-1.6, #7189): `lib/db/helper-paths-export.ts`, `lib/db/feature-entitlements.ts`.
 *
 * A scripted query target stands in for Postgres. Each test pins how many statements a read
 * issues (a fixed number, whatever the number of rows) and how the rows are assembled.
 */

import { describe, test, expect, jest, beforeEach } from '@jest/globals';

type Rows = Record<string, unknown>[];
type Call = { sql: string; params: unknown[] };

const poolCalls: Call[] = [];
let poolAnswer: (sql: string, params: unknown[]) => Rows = () => [];

jest.mock('../lib/db/db', () => ({
  query: async (sql: string, params: unknown[] = []) => {
    poolCalls.push({ sql, params });
    const rows = poolAnswer(sql, params);
    return { rows, rowCount: rows.length };
  },
}));

import {
  loadPathsForOpenAPIExport,
  loadReferencedClassesForPaths,
  PATHS_EXPORT_QUERIES,
  readPathsForOpenAPIExport,
  type PathsQueryable,
} from '../lib/db/helper-paths-export';
import { getEntitledFeatureFlagNames, userHasFeatureFlag } from '../lib/db/feature-entitlements';

/** A client answering each `PATHS_EXPORT_QUERIES` statement from `tables`. */
function scripted(tables: Partial<Record<keyof typeof PATHS_EXPORT_QUERIES, Rows>>): PathsQueryable & {
  calls: Call[];
} {
  const calls: Call[] = [];
  return {
    calls,
    query: async (sql: string, params: unknown[] = []) => {
      calls.push({ sql, params });
      const key = (Object.keys(PATHS_EXPORT_QUERIES) as Array<keyof typeof PATHS_EXPORT_QUERIES>).find(
        (name) => PATHS_EXPORT_QUERIES[name] === sql,
      );
      return { rows: key ? (tables[key] ?? []) : [] };
    },
  };
}

beforeEach(() => {
  poolCalls.length = 0;
  poolAnswer = () => [];
});

describe('readPathsForOpenAPIExport', () => {
  test('assembles operations, descriptions, parameters, bodies and responses per path', async () => {
    const client = scripted({
      paths: [
        { id: 'p1', pathname: '/pets', summary: 'Pets', description: null },
        { id: 'p2', pathname: '/stores', summary: null, description: 'Stores' },
      ],
      operations: [
        { id: 'o1', version_path_id: 'p1', operation: 'GET', metadata: null },
        { id: 'o2', version_path_id: 'p1', operation: 'QUERY', metadata: '{"httpMethod":"QUERY"}' },
        { id: 'o3', version_path_id: 'p2', operation: 'POST', metadata: {} },
      ],
      descriptions: [
        {
          op_key: 'o1', id: 'd1', summary: 'List', description: null, operation_id: 'listPets',
          tags: '["pets"]', deprecated: null, external_docs: null, security: '{"key":[]}',
          security_description: null, x_security_description: 'Key needed', x_private_meta: null,
          x_private_alt: true,
        },
      ],
      parameters: [
        { op_key: 'o1', id: 'pa1', name: 'limit', in_location: 'query', summary: null, description: null, data: '{"type":"integer"}' },
        { op_key: 'o3', id: 'pa2', name: 'id', in_location: 'path', summary: null, description: null, data: null },
      ],
      requestBodies: [
        {
          op_key: 'o3', id: 'rb1', name: 'Store', description: null, required: true,
          content_types: [
            { id: 'c1', media_type: 'application/json', class_id: 'k1', class_name: 'Store', inline_schema: null, encoding: null, examples: '[1]', item_schema: null },
          ],
        },
      ],
      responses: [
        {
          op_key: 'o1', id: 'r1', status_code: '200', description: 'OK', data: null, class_id: null,
          class_name: null, inline_schema: '{"type":"array"}',
          content_types: [{ id: 'rc1', media_type: 'application/json', item_schema: true }],
        },
      ],
    });

    const paths = await readPathsForOpenAPIExport(client, 'v1');

    expect(client.calls).toHaveLength(6);
    expect(client.calls.every((c) => c.params[0] === 'v1')).toBe(true);
    expect(paths.map((p) => [p.pathname, p.operations.map((o) => o.id)])).toEqual([
      ['/pets', ['o1', 'o2']],
      ['/stores', ['o3']],
    ]);
    const [get, query] = paths[0].operations;
    expect(get.description).toEqual({
      id: 'd1', summary: 'List', description: null, operationId: 'listPets', tags: ['pets'],
      deprecated: null, externalDocs: undefined, security: [{ key: [] }],
      securityDescription: 'Key needed', 'x-private': true,
    });
    expect(get.parameters).toEqual([
      { id: 'pa1', name: 'limit', in_location: 'query', summary: null, description: null, data: { type: 'integer' } },
    ]);
    expect(get.requestBody).toBeNull();
    expect(get.responses[0].inline_schema).toEqual({ type: 'array' });
    expect(get.responses[0].content_types[0].item_schema).toBe(true);
    expect(query).toMatchObject({ httpMethod: 'QUERY', description: undefined, parameters: [], responses: [] });
    const post = paths[1].operations[0];
    expect(post.parameters[0].data).toEqual({});
    expect(post.requestBody?.content_types[0]).toEqual({
      id: 'c1', media_type: 'application/json', class_id: 'k1', class_name: 'Store',
      inline_schema: null, encoding: null, examples: [1], item_schema: false,
    });
  });

  test('a version without paths is one statement; paths without operations are two', async () => {
    const none = scripted({});
    expect(await readPathsForOpenAPIExport(none, 'v1')).toEqual([]);
    expect(none.calls).toHaveLength(1);

    const bare = scripted({ paths: [{ id: 'p1', pathname: '/a', summary: null, description: null }] });
    expect(await readPathsForOpenAPIExport(bare, 'v1')).toEqual([
      { id: 'p1', pathname: '/a', summary: null, description: null, operations: [] },
    ]);
    expect(bare.calls).toHaveLength(2);
  });

  test('content types keep their stored order in the set-based reads', () => {
    expect(PATHS_EXPORT_QUERIES.requestBodies).toContain('ORDER BY rbc.ctid');
    expect(PATHS_EXPORT_QUERIES.responses).toContain('ORDER BY rc.ctid');
    for (const sql of Object.values(PATHS_EXPORT_QUERIES)) {
      expect(sql).toContain('version_id = $1');
    }
  });
});

describe('loadPathsForOpenAPIExport', () => {
  test("runs on the caller's client when one is given", async () => {
    const client = scripted({ paths: [] });
    expect(JSON.parse(await loadPathsForOpenAPIExport('v1', client))).toEqual({ success: true, paths: [] });
    expect(client.calls).toHaveLength(1);
    expect(poolCalls).toHaveLength(0);
  });

  test('defaults to the pool and reports a failed read', async () => {
    poolAnswer = () => {
      throw new Error('boom');
    };
    expect(JSON.parse(await loadPathsForOpenAPIExport('v1'))).toEqual({ success: false, error: 'boom' });
    expect(poolCalls).toHaveLength(1);
  });
});

describe('loadReferencedClassesForPaths', () => {
  test("reads every class's properties in one statement", async () => {
    poolAnswer = (sql) =>
      sql.includes('FROM apiome.classes')
        ? [
            { id: 'k1', name: 'Pet', description: null, schema: '{"type":"object"}' },
            { id: 'k2', name: 'Tag', description: null, schema: null },
          ]
        : [
            { id: 'cp1', name: 'id', description: null, data: '{"type":"string"}', parent_id: null, class_id: 'k1' },
            { id: 'cp2', name: 'name', description: null, data: null, parent_id: null, class_id: 'k1' },
          ];
    const result = JSON.parse(await loadReferencedClassesForPaths('v1', ['Pet', 'Tag']));
    expect(poolCalls).toHaveLength(2);
    expect(poolCalls[1].sql).toContain('class_id = ANY($1::uuid[])');
    expect(poolCalls[1].params).toEqual([['k1', 'k2']]);
    expect(result).toEqual({
      success: true,
      classes: [
        {
          id: 'k1', name: 'Pet', description: null, schema: { type: 'object' },
          properties: [
            { id: 'cp1', name: 'id', description: null, data: { type: 'string' }, parent_id: null },
            { id: 'cp2', name: 'name', description: null, data: {}, parent_id: null },
          ],
        },
        { id: 'k2', name: 'Tag', description: null, schema: {}, properties: [] },
      ],
    });
  });

  test('no matching class reads no properties', async () => {
    expect(JSON.parse(await loadReferencedClassesForPaths('v1', ['Missing']))).toEqual({ success: true, classes: [] });
    expect(poolCalls).toHaveLength(1);
  });
});

describe('getEntitledFeatureFlagNames', () => {
  const row = (name: string, grants: Partial<Record<string, boolean | null>>) => ({
    name, flag_enabled: true, user_override: null, tenant_override: null, license_grant: false, ...grants,
  });

  test('resolves every candidate in one statement with the single-flag precedence', async () => {
    poolAnswer = () => [
      row('a', { user_override: true }),
      row('b', { user_override: false, tenant_override: true, license_grant: true }),
      row('c', { tenant_override: true }),
      row('d', { license_grant: true }),
      row('e', {}),
      row('f', { flag_enabled: false, user_override: true }),
      { name: 'g', flag_enabled: null, user_override: null, tenant_override: null, license_grant: null },
    ];
    const names = await getEntitledFeatureFlagNames('u1', 't1', ['a', 'b', 'c', 'd', 'e', 'f', 'g']);
    expect(names).toEqual(['a', 'c', 'd']);
    expect(poolCalls).toHaveLength(1);
    expect(poolCalls[0].params).toEqual([['a', 'b', 'c', 'd', 'e', 'f', 'g'], 'u1', 't1']);
    expect(poolCalls[0].sql).toContain('LEFT JOIN LATERAL');
  });

  test('without candidates it checks every enabled flag, still in one statement', async () => {
    poolAnswer = () => [row('x', { license_grant: true })];
    expect(await getEntitledFeatureFlagNames('u1')).toEqual(['x']);
    expect(poolCalls).toHaveLength(1);
    expect(poolCalls[0].params).toEqual([null, 'u1', null]);
  });

  test('userHasFeatureFlag keeps its precedence', async () => {
    poolAnswer = () => [row('a', { tenant_override: false, license_grant: true })];
    expect(await userHasFeatureFlag('u1', 't1', 'a')).toBe(false);
    poolAnswer = () => [];
    expect(await userHasFeatureFlag('u1', 't1', 'a')).toBe(false);
  });
});
