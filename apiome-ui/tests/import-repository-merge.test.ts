/**
 * Multi-repository merge wiring in the import (REPO-5.7, #2792).
 *
 * Drives `startImport` for a repository file imported into a project that already holds another
 * repository's content. Storage is mocked (`lib/db/repository-merge` loaders and writer, the
 * transaction helpers, the path importer); the merge rules are the real ones.
 */

import { describe, test, expect, beforeEach, afterEach, jest } from '@jest/globals';
import type { MergeSource, ParentEntity } from '../lib/repository-merge';

const mockClient = { query: jest.fn(), release: jest.fn() };
const mockCreateVersionTx = jest.fn((..._args: any[]) =>
  Promise.resolve(JSON.stringify({ success: true, version: { id: 'ver-2' } })),
);
const mockBegin = jest.fn((..._args: any[]) => Promise.resolve());
const mockCommit = jest.fn((..._args: any[]) => Promise.resolve());
const mockMergeProjectFields = jest.fn((..._args: any[]) => Promise.resolve(JSON.stringify({ success: true })));

jest.mock('../lib/db/import-transaction', () => ({
  getTransactionClient: jest.fn(() => Promise.resolve(mockClient)),
  beginTransaction: (...args: any[]) => mockBegin(...args),
  commitTransaction: (...args: any[]) => mockCommit(...args),
  rollbackTransaction: jest.fn(() => Promise.resolve()),
  releaseClient: jest.fn(() => Promise.resolve()),
  createProjectTx: jest.fn(() => Promise.resolve(JSON.stringify({ success: true, project: { id: 'proj-new' } }))),
  mergeProjectImportOpenApiFieldsTx: (...args: any[]) => mockMergeProjectFields(...args),
  createVersionTx: (...args: any[]) => mockCreateVersionTx(...args),
  createPropertyTx: jest.fn(() => Promise.resolve(JSON.stringify({ success: true, property: { id: 'prop-1' } }))),
  createPropertiesBatchTx: jest.fn((_c: any, rows: any[]) =>
    Promise.resolve(JSON.stringify({ success: true, inserted: Array.isArray(rows) ? rows.length : 0, failed: [] })),
  ),
  createClassTx: jest.fn(() => Promise.resolve(JSON.stringify({ success: true, class: { id: 'class-1' } }))),
  addPropertyToClassTx: jest.fn(() => Promise.resolve(JSON.stringify({ success: true, classProperty: { id: 'cp-1' } }))),
  addPropertiesToClassBatchTx: jest.fn((_c: any, rows: any[]) =>
    Promise.resolve(JSON.stringify({ success: true, inserted: Array.isArray(rows) ? rows.length : 0, failed: [] })),
  ),
  getClassesWithPropertiesAndTagsTx: jest.fn(() =>
    Promise.resolve(JSON.stringify([{ name: 'Invoice', schema: {}, properties: [] }])),
  ),
  getLatestVersionUuidForProjectTx: jest.fn(() => Promise.resolve('ver-1')),
  getProjectIdBySlugTx: jest.fn(() => Promise.resolve('proj-1')),
  getVersionUuidForCatalogVersionLineTx: jest.fn(() => Promise.resolve(null)),
  listProjectLibraryPropertiesTx: jest.fn(() => Promise.resolve([])),
}));

let mockClassNames = ['Invoice'];
jest.mock('../lib/importers', () => ({
  getImporter: jest.fn(() => ({
    kind: 'openapi',
    normalize: () => ({
      classes: mockClassNames.map((name) => ({ name, description: null, schema: { type: 'object' }, properties: [] })),
      warnings: [] as string[],
    }),
  })),
  ImportSourceKind: { openapi: 'openapi' },
}));

jest.mock('../lib/db/repository-import-metrics', () => ({
  recordTenantRepositoryImport: jest.fn(() => Promise.resolve(true)),
  upsertRepositoryImportSpec: jest.fn(() => Promise.resolve(true)),
}));

const mockImportPaths = jest.fn((..._args: any[]) => Promise.resolve({ success: true }));
jest.mock('../lib/db/import-openapi-paths-security', () => ({
  importOpenAPIPathsAndSecurity: (...args: any[]) => mockImportPaths(...args),
}));

const users: MergeSource = {
  sourceId: 'src-users',
  repositoryId: 'repo-users',
  repositoryFullName: 'acme/users',
  branch: 'main',
  path: 'openapi.yaml',
  precedence: 1,
};
const billing: MergeSource = {
  sourceId: null,
  repositoryId: 'repo-billing',
  repositoryFullName: 'acme/billing',
  branch: 'main',
  path: 'spec.yaml',
  precedence: null,
};
let mockParent: ParentEntity[] = [];
const mockLoadIncoming = jest.fn((..._args: any[]) => Promise.resolve(billing as MergeSource | null));
const mockApply = jest.fn((..._args: any[]) => Promise.resolve({ sourceId: 'src-billing', classesCarried: 1, provenanceRows: 4 }));
const carriedPath = { path: '/users', operations: [] };
jest.mock('../lib/db/repository-merge', () => ({
  loadIncomingSource: (...args: any[]) => mockLoadIncoming(...args),
  loadParentEntities: jest.fn(() => Promise.resolve(mockParent)),
  loadCarriedPaths: jest.fn((_v: string, names: string[]) =>
    Promise.resolve(names.includes('/users') ? [carriedPath] : []),
  ),
  applyRepositoryMerge: (...args: any[]) => mockApply(...args),
}));

const DOCUMENT = {
  openapi: '3.1.0',
  info: { title: 'Billing', version: '1.1.0' },
  paths: { '/invoices': { get: { responses: { '200': { description: 'OK' } } } } },
};

function input(overrides: Record<string, any> = {}) {
  return {
    tenantId: 'tenant-1',
    userId: 'user-1',
    sourceKind: 'openapi' as const,
    document: DOCUMENT,
    project: { name: 'Shop', slug: 'shop', description: null },
    version: { versionId: '1.1.0', description: null },
    existingProjectId: 'proj-1',
    options: { selectedSchemas: [] as string[], ...(overrides.options ?? {}) },
    repositorySource: { repositoryId: 'repo-billing', branch: 'main', path: 'spec.yaml', blobSha: 'b2' },
    ...overrides,
  };
}

async function settle(helper: typeof import('../lib/db/import-helper'), jobId: string, done: (s: string) => boolean) {
  const start = Date.now();
  while (Date.now() - start < 5000) {
    const status = await helper.getImportStatus(jobId);
    if (done(status.state)) return status;
    await new Promise((r) => setTimeout(r, 20));
  }
  throw new Error('import did not settle');
}
const terminal = (s: string) => ['pending-approval', 'completed', 'failed', 'canceled'].includes(s);

describe('startImport — multi-repository merge (REPO-5.7)', () => {
  beforeEach(() => {
    mockClassNames = ['Invoice'];
    mockParent = [
      { kind: 'class', key: 'User', source: users },
      { kind: 'path', key: '/users', source: users },
    ];
    mockCreateVersionTx.mockClear();
    mockApply.mockClear();
    mockImportPaths.mockClear();
    mockLoadIncoming.mockClear();
    mockBegin.mockClear();
    mockCommit.mockClear();
    mockMergeProjectFields.mockClear();
  });
  afterEach(() => jest.resetModules());

  test('a class another repository defines fails the import before a version is created', async () => {
    mockClassNames = ['User', 'Invoice'];
    const helper = await import('../lib/db/import-helper');
    const { jobId } = await helper.startImport(input());
    const status = await settle(helper, jobId, terminal);

    expect(status.state).toBe('failed');
    const failed = status.events.find((e: any) => e.code === 'FAILED');
    expect(failed?.message).toBe(
      'Repository merge conflict in project "Shop": 1 definition collides. ' +
        'class "User" is defined by acme/users (main:openapi.yaml) and acme/billing (main:spec.yaml). ' +
        'Each class and path must come from one repository: rename or remove the duplicate in one of the files, then import again.',
    );
    const conflict = status.events.find((e: any) => e.code === 'REPOSITORY_MERGE_CONFLICT');
    expect(conflict?.context.conflicts).toEqual([
      { kind: 'class', key: 'User', existing: 'acme/users (main:openapi.yaml)', incoming: 'acme/billing (main:spec.yaml)' },
    ]);
    expect(mockCreateVersionTx).not.toHaveBeenCalled();
    expect(mockApply).not.toHaveBeenCalled();
  });

  test('a path another repository defines fails the import too', async () => {
    mockParent = [{ kind: 'path', key: '/invoices', source: users }];
    const helper = await import('../lib/db/import-helper');
    const { jobId } = await helper.startImport(input());
    const status = await settle(helper, jobId, terminal);
    expect(status.state).toBe('failed');
    expect(status.events.find((e: any) => e.code === 'FAILED')?.message).toContain('path "/invoices" is defined by acme/users');
  });

  test('a dry run reports the same conflict and writes nothing', async () => {
    mockClassNames = ['User'];
    const helper = await import('../lib/db/import-helper');
    const { jobId } = await helper.startImport(input({ options: { selectedSchemas: [], dryRun: true } }));
    const status = await settle(helper, jobId, terminal);
    expect(status.state).toBe('failed');
    expect(status.events.find((e: any) => e.code === 'FAILED')?.message).toMatch(/^Repository merge conflict/);
    expect(mockCreateVersionTx).not.toHaveBeenCalled();
  });

  test('a conflict-free dry run summarizes what would be carried', async () => {
    const helper = await import('../lib/db/import-helper');
    const { jobId } = await helper.startImport(input({ options: { selectedSchemas: [], dryRun: true } }));
    const status = await settle(helper, jobId, terminal);
    expect(status.state).toBe('completed');
    expect(status.summary.repositoryMerge).toEqual({ sources: 2, classesCarried: 1, pathsCarried: 1 });
    expect(status.events.find((e: any) => e.code === 'REPOSITORY_MERGE')?.message).toBe(
      'Merging 2 repository files: carrying forward 1 class and 1 path from other files.',
    );
    expect(mockApply).not.toHaveBeenCalled();
  });

  test('a merge writes carried content in the transaction and the carried paths after commit', async () => {
    const helper = await import('../lib/db/import-helper');
    const { jobId } = await helper.startImport(input());
    const pending = await settle(helper, jobId, terminal);
    expect(pending.state).toBe('pending-approval');

    expect(mockApply).toHaveBeenCalledTimes(1);
    const applied = mockApply.mock.calls[0][1] as any;
    expect(applied).toMatchObject({
      tenantId: 'tenant-1',
      projectId: 'proj-1',
      versionId: 'ver-2',
      parentVersionId: 'ver-1',
      incoming: billing,
      incomingClasses: ['Invoice'],
      incomingPaths: ['/invoices'],
    });
    expect(applied.plan.mode).toBe('multi-source');
    expect(applied.plan.carried.map((e: any) => e.key)).toEqual(['User', '/users']);

    await helper.commitImport(jobId);
    const done = await settle(helper, jobId, (s) => s === 'completed' || s === 'failed');
    expect(done.state).toBe('completed');
    const [versionId, paths] = mockImportPaths.mock.calls[0] as any[];
    expect(versionId).toBe('ver-2');
    expect(paths.map((p: any) => p.path)).toEqual(['/invoices', '/users']);
    expect(done.events.find((e: any) => e.code === 'IMPORTING_PATHS')?.message).toBe(
      'Importing 2 path(s) (1 carried forward from other repository files) and 0 security scheme(s)...',
    );
    expect(done.summary.pathsImported).toBe(1);
  });

  test('a lower-precedence file only fills in missing project metadata', async () => {
    const helper = await import('../lib/db/import-helper');
    const { jobId } = await helper.startImport(input({ projectMetadata: { contact: { name: 'Billing team' } } }));
    await settle(helper, jobId, terminal);
    expect(mockMergeProjectFields).toHaveBeenCalledTimes(1);
    expect((mockMergeProjectFields.mock.calls[0] as any[])[2]).toMatchObject({
      metadataPatch: { contact: { name: 'Billing team' } },
      metadataFillOnly: true,
    });
  });

  test('the first contributing file still sets the project metadata', async () => {
    const helper = await import('../lib/db/import-helper');
    mockLoadIncoming.mockResolvedValueOnce(users);
    mockParent = [
      { kind: 'class', key: 'User', source: users },
      { kind: 'class', key: 'Invoice', source: { ...billing, sourceId: 'src-billing', precedence: 2 } },
    ];
    mockClassNames = ['User'];
    const { jobId } = await helper.startImport(input({ projectMetadata: { contact: { name: 'Users team' } } }));
    await settle(helper, jobId, terminal);
    expect((mockMergeProjectFields.mock.calls[0] as any[])[2]).toMatchObject({ metadataFillOnly: false });
  });

  test('a conflict fails before the project metadata is touched', async () => {
    mockClassNames = ['User'];
    const helper = await import('../lib/db/import-helper');
    const { jobId } = await helper.startImport(input({ projectMetadata: { contact: { name: 'x' } } }));
    expect((await settle(helper, jobId, terminal)).state).toBe('failed');
    expect(mockMergeProjectFields).not.toHaveBeenCalled();
  });

  test('incremental mode applies the merge in its own transaction', async () => {
    const helper = await import('../lib/db/import-helper');
    const { jobId } = await helper.startImport(input({ options: { selectedSchemas: [], incrementalMode: true } }));
    const status = await settle(helper, jobId, (s) => s === 'completed' || s === 'failed');
    expect(status.state).toBe('completed');
    expect(mockApply).toHaveBeenCalledTimes(1);
    expect(mockImportPaths.mock.calls[0][1].map((p: any) => p.path)).toEqual(['/invoices', '/users']);
  });

  test('an import that is not from a repository file is untouched', async () => {
    const helper = await import('../lib/db/import-helper');
    const { jobId } = await helper.startImport(input({ repositorySource: undefined }));
    const status = await settle(helper, jobId, terminal);
    expect(status.state).toBe('pending-approval');
    expect(mockLoadIncoming).not.toHaveBeenCalled();
    expect(mockApply).not.toHaveBeenCalled();
  });

  test('an unregistered repository imports without merge or provenance', async () => {
    mockLoadIncoming.mockResolvedValueOnce(null);
    const helper = await import('../lib/db/import-helper');
    const { jobId } = await helper.startImport(input());
    const status = await settle(helper, jobId, terminal);
    expect(status.state).toBe('pending-approval');
    expect(mockApply).not.toHaveBeenCalled();
  });
});
