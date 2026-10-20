/**
 * Multi-repository merge storage (REPO-5.7, #2792): `lib/db/repository-merge.ts`.
 *
 * A scripted query target stands in for Postgres: each test asserts the statements the module
 * issues, their parameters, and how it reads the rows back. The SQL itself was exercised against a
 * live database while building the feature; these tests pin the contract.
 */

import { describe, test, expect, jest, beforeEach } from '@jest/globals';

jest.mock('../lib/db/helper-paths-export', () => ({
  loadPathsForOpenAPIExport: jest.fn(),
}));

import { loadPathsForOpenAPIExport } from '../lib/db/helper-paths-export';
import {
  applyRepositoryMerge,
  copyClassesTx,
  loadCarriedPaths,
  loadIncomingSource,
  loadParentEntities,
  type DbRow,
  type Queryable,
} from '../lib/db/repository-merge';
import { planRepositoryMerge, type MergeSource } from '../lib/repository-merge';

type Call = { sql: string; params: unknown[] };

/** A query target answering each statement with the first handler whose pattern matches. */
function scripted(handlers: Array<[RegExp, (params: unknown[]) => DbRow[]]>): Queryable & { calls: Call[] } {
  const calls: Call[] = [];
  return {
    calls,
    query: async (sql: string, params: unknown[] = []) => {
      calls.push({ sql, params });
      const hit = handlers.find(([re]) => re.test(sql));
      return { rows: hit ? hit[1](params) : [] };
    },
  };
}

const users: MergeSource = {
  sourceId: 'src-users',
  repositoryId: 'repo-users',
  repositoryFullName: 'acme/users',
  branch: 'main',
  path: 'openapi.yaml',
  precedence: 1,
  blobSha: 'b1',
};
const billing: MergeSource = {
  sourceId: null,
  repositoryId: 'repo-billing',
  repositoryFullName: 'acme/billing',
  branch: 'main',
  path: 'spec.yaml',
  precedence: null,
  blobSha: 'b2',
};

describe('loadIncomingSource', () => {
  test('returns the file with its existing source row', async () => {
    const q = scripted([
      [/FROM apiome\.tenant_repositories tr/, () => [{ repository_full_name: 'acme/users', source_id: 's1', precedence: 3 }]],
    ]);
    const source = await loadIncomingSource(q, 't1', 'p1', { repositoryId: 'r1', branch: 'main', path: 'a.yaml', blobSha: 'x' });
    expect(source).toEqual({
      sourceId: 's1',
      repositoryId: 'r1',
      repositoryFullName: 'acme/users',
      branch: 'main',
      path: 'a.yaml',
      precedence: 3,
      blobSha: 'x',
    });
    expect(q.calls[0].params).toEqual(['t1', 'r1', 'p1', 'main', 'a.yaml']);
    expect(q.calls[0].sql).toMatch(/tr\.tenant_id = \$1::uuid AND tr\.deleted_at IS NULL/);
  });

  test('a repository that is not the tenant’s yields null (no merge, no provenance)', async () => {
    const q = scripted([]);
    expect(await loadIncomingSource(q, 't1', null, { repositoryId: 'r1', branch: 'main', path: 'a.yaml' })).toBeNull();
  });
});

describe('loadParentEntities', () => {
  test('maps provenance rows; a removed source reads as unattributed', async () => {
    const q = scripted([
      [
        /WITH ents AS/,
        () => [
          { kind: 'class', key: 'User', has_row: true, source_id: 's1', precedence: 1, repository_id: 'r1', repository_full_name: 'acme/users', branch: 'main', path: 'a.yaml', blob_sha: 'b' },
          { kind: 'class', key: 'Gone', has_row: true, source_id: null, precedence: null, repository_id: null, repository_full_name: 'acme/old', branch: null, path: null, blob_sha: null },
          { kind: 'path', key: '/x', has_row: false, source_id: null },
        ],
      ],
    ]);
    const entities = await loadParentEntities(q, 't1', 'p1', 'v1');
    expect(entities).toEqual([
      {
        kind: 'class',
        key: 'User',
        source: { sourceId: 's1', repositoryId: 'r1', repositoryFullName: 'acme/users', branch: 'main', path: 'a.yaml', precedence: 1, blobSha: 'b' },
      },
      { kind: 'class', key: 'Gone', source: null },
      { kind: 'path', key: '/x', source: null },
    ]);
    // Provenance exists, so the pre-REPO-5.7 import table is not consulted.
    expect(q.calls).toHaveLength(1);
  });

  test('a version with no provenance is attributed to the repository file it was imported from', async () => {
    const q = scripted([
      [/WITH ents AS/, () => [{ kind: 'class', key: 'User', has_row: false }, { kind: 'path', key: '/users', has_row: false }]],
      [
        /FROM apiome\.tenant_repository_imports tri/,
        () => [{ repository_id: 'r1', branch: 'main', path: 'a.yaml', blob_sha: 'b', repository_full_name: 'acme/users', source_id: null, precedence: null }],
      ],
    ]);
    const entities = await loadParentEntities(q, 't1', 'p1', 'v1');
    expect(entities.map((e) => `${e.kind}:${e.key}:${e.source?.repositoryFullName}:${e.source?.sourceId}`)).toEqual([
      'class:User:acme/users:null',
      'path:/users:acme/users:null',
    ]);
    expect(q.calls[1].params).toEqual(['t1', 'p1', 'v1']);
  });

  test('no provenance and no import row: everything is unattributed', async () => {
    const q = scripted([[/WITH ents AS/, () => [{ kind: 'class', key: 'User', has_row: false }]]]);
    expect(await loadParentEntities(q, 't1', 'p1', 'v1')).toEqual([{ kind: 'class', key: 'User', source: null }]);
  });
});

describe('loadCarriedPaths', () => {
  const mockLoad = loadPathsForOpenAPIExport as jest.MockedFunction<typeof loadPathsForOpenAPIExport>;
  beforeEach(() => mockLoad.mockReset());

  test('nothing to carry reads nothing', async () => {
    expect(await loadCarriedPaths('v1', [])).toEqual([]);
    expect(mockLoad).not.toHaveBeenCalled();
  });

  test('exports the parent paths and keeps only the carried ones, parsed for import', async () => {
    const op = (operation: string) => ({
      id: `op-${operation}`,
      operation,
      parameters: [],
      requestBody: null,
      responses: [{ status_code: '200', description: 'OK', content: [] }],
      description: { summary: 'S', description: null, operation_id: `${operation.toLowerCase()}Op` },
    });
    mockLoad.mockResolvedValue(
      JSON.stringify({
        success: true,
        paths: [
          { id: 'p1', pathname: '/users', summary: null, description: null, operations: [op('GET')] },
          { id: 'p2', pathname: '/other', summary: null, description: null, operations: [op('POST')] },
        ],
      }),
    );
    const paths = await loadCarriedPaths('v1', ['/users']);
    expect(mockLoad).toHaveBeenCalledWith('v1');
    expect(paths.map((p) => p.path)).toEqual(['/users']);
    expect(paths[0].operations).toHaveLength(1);
  });

  test('a failed read fails the merge instead of silently dropping paths', async () => {
    mockLoad.mockResolvedValue(JSON.stringify({ success: false, error: 'boom' }));
    await expect(loadCarriedPaths('v1', ['/users'])).rejects.toThrow(/carried forward.*boom/);
  });
});

describe('copyClassesTx', () => {
  test('copies the named classes, then every property link in one statement', async () => {
    const q = scripted([[/INSERT INTO apiome\.classes/, () => [{ old_id: 'c-old', new_id: 'c-new' }]]]);
    expect(await copyClassesTx(q, 'v1', 'v2', ['User'])).toBe(1);
    expect(q.calls[0].params).toEqual(['v1', 'v2', ['User']]);
    expect(q.calls[1].sql).toMatch(/INSERT INTO apiome\.class_properties/);
    expect(q.calls[1].sql).toMatch(/LEFT JOIN m pm ON pm\.old_id = m\.parent_id/);
    expect(q.calls[1].params).toEqual([['c-old'], ['c-new']]);
  });

  test('no names issues no statement', async () => {
    const q = scripted([]);
    expect(await copyClassesTx(q, 'v1', 'v2', [])).toBe(0);
    expect(q.calls).toHaveLength(0);
  });
});

describe('applyRepositoryMerge', () => {
  function client() {
    let next = 0;
    return scripted([
      [/INSERT INTO apiome\.project_repository_sources/, () => [{ id: `new-src-${++next}` }]],
      [/INSERT INTO apiome\.classes/, () => [{ old_id: 'c-old', new_id: 'c-new' }]],
    ]);
  }

  test('multi-source: source rows, carried classes and schemes, then provenance', async () => {
    const plan = planRepositoryMerge({
      incoming: billing,
      incomingClasses: ['Invoice'],
      incomingPaths: ['/invoices'],
      parentEntities: [
        { kind: 'class', key: 'User', source: users },
        { kind: 'path', key: '/users', source: users },
        { kind: 'class', key: 'Note', source: null },
      ],
    });
    const q = client();
    const result = await applyRepositoryMerge(q, {
      tenantId: 't1',
      projectId: 'p1',
      userId: 'u1',
      versionId: 'v2',
      parentVersionId: 'v1',
      incoming: billing,
      plan,
      incomingClasses: ['Invoice'],
      incomingPaths: ['/invoices'],
    });

    const kinds = q.calls.map((c) =>
      /project_repository_sources/.test(c.sql)
        ? 'source'
        : /INSERT INTO apiome\.classes/.test(c.sql)
          ? 'classes'
          : /class_properties/.test(c.sql)
            ? 'properties'
            : /version_security_scheme/.test(c.sql)
              ? 'schemes'
              : /version_entity_sources/.test(c.sql)
                ? 'provenance'
                : c.sql,
    );
    // users already has a source row, so only the incoming file is upserted.
    expect(kinds).toEqual(['source', 'classes', 'properties', 'schemes', 'provenance']);
    expect(q.calls[0].params).toEqual(['t1', 'p1', 'repo-billing', 'main', 'spec.yaml', 'v2', 'b2', 'u1', true]);
    // The carried classes are User and the unattributed Note.
    expect(q.calls[1].params[2]).toEqual(['User', 'Note']);

    const provenance = q.calls[4].params;
    expect(provenance[0]).toBe('v2');
    expect(provenance[1]).toEqual(['class', 'path', 'class', 'path']);
    expect(provenance[2]).toEqual(['Invoice', '/invoices', 'User', '/users']);
    expect(provenance[3]).toEqual(['new-src-1', 'new-src-1', 'src-users', 'src-users']);
    expect(provenance[9]).toEqual([null, null, 'v1', 'v1']);
    expect(result).toEqual({ sourceId: 'new-src-1', classesCarried: 1, provenanceRows: 4 });
  });

  test('a carried file without a source row (pre-REPO-5.7 import) is recorded before the incoming file', async () => {
    const legacy: MergeSource = { ...users, sourceId: null, precedence: null };
    const plan = planRepositoryMerge({
      incoming: billing,
      incomingClasses: [],
      incomingPaths: [],
      parentEntities: [{ kind: 'class', key: 'User', source: legacy }],
    });
    const q = client();
    await applyRepositoryMerge(q, {
      tenantId: 't1',
      projectId: 'p1',
      userId: 'u1',
      versionId: 'v2',
      parentVersionId: 'v1',
      incoming: billing,
      plan,
      incomingClasses: [],
      incomingPaths: [],
    });
    const sourceCalls = q.calls.filter((c) => /project_repository_sources/.test(c.sql));
    expect(sourceCalls.map((c) => c.params[2])).toEqual(['repo-users', 'repo-billing']);
    // The legacy file's first/last version is the parent, and an existing row is not touched.
    expect(sourceCalls[0].params[5]).toBe('v1');
    expect(sourceCalls[0].params[8]).toBe(false);
    const provenance = q.calls.find((c) => /version_entity_sources/.test(c.sql))!;
    expect(provenance.params[3]).toEqual(['new-src-1']);
  });

  test('single-source: only the source row and the incoming provenance', async () => {
    const plan = planRepositoryMerge({ incoming: billing, incomingClasses: ['A'], incomingPaths: [], parentEntities: [] });
    const q = client();
    await applyRepositoryMerge(q, {
      tenantId: 't1',
      projectId: 'p1',
      userId: 'u1',
      versionId: 'v1',
      parentVersionId: null,
      incoming: billing,
      plan,
      incomingClasses: ['A', 'A'],
      incomingPaths: [],
    });
    expect(q.calls).toHaveLength(2);
    expect(q.calls[1].params[2]).toEqual(['A']);
  });

  test('refuses a plan with conflicts', async () => {
    const plan = planRepositoryMerge({
      incoming: billing,
      incomingClasses: ['User'],
      incomingPaths: [],
      parentEntities: [{ kind: 'class', key: 'User', source: users }],
    });
    await expect(
      applyRepositoryMerge(client(), {
        tenantId: 't1',
        projectId: 'p1',
        userId: 'u1',
        versionId: 'v2',
        parentVersionId: 'v1',
        incoming: billing,
        plan,
        incomingClasses: ['User'],
        incomingPaths: [],
      }),
    ).rejects.toThrow(/unresolved conflict/);
  });
});
