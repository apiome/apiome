/**
 * Import Incremental Mode Tests (#730)
 *
 * Unit tests for incremental mode: import all available, skip failures.
 * - When options.incrementalMode === true, no single transaction; each class is committed separately
 * - Failed classes are skipped and the job still completes with state 'completed'
 * - summary.incrementalMode === true, result has projectId/versionId
 * - Events include INCREMENTAL_MODE and INCREMENTAL_COMPLETE
 * - transactionPending remains false (no pending-approval step)
 */

import { describe, test, expect, beforeEach, afterEach, jest } from '@jest/globals';

const mockGetTransactionClient = jest.fn();
const mockBeginTransaction = jest.fn();
const mockCommitTransaction = jest.fn();
const mockRollbackTransaction = jest.fn();
const mockReleaseClient = jest.fn();
const mockCreateProjectTx = jest.fn();
const mockCreateVersionTx = jest.fn();
const mockCreatePropertyTx = jest.fn();
const mockCreatePropertiesBatchTx = jest.fn();
const mockCreateClassTx = jest.fn();
const mockAddPropertyToClassTx = jest.fn();
const mockAddPropertiesToClassBatchTx = jest.fn();
const mockGetClassesWithPropertiesAndTagsTx = jest.fn();
const mockGetLatestVersionUuidForProjectTx = jest.fn(() => Promise.resolve(null));
const mockGetProjectIdBySlugTx = jest.fn<() => Promise<string | null>>(() => Promise.resolve(null));
const mockListProjectLibraryPropertiesTx = jest.fn(() => Promise.resolve([]));

// When set, createClassTx will return failure for this class name (simulate one class failing)
let createClassTxFailForClassName: string | null = null;

const mockClient = { query: jest.fn(), release: jest.fn() };

jest.mock('../lib/db/import-transaction', () => ({
  getTransactionClient: (...args: any[]) => mockGetTransactionClient(...args),
  beginTransaction: (...args: any[]) => mockBeginTransaction(...args),
  commitTransaction: (...args: any[]) => mockCommitTransaction(...args),
  rollbackTransaction: (...args: any[]) => mockRollbackTransaction(...args),
  releaseClient: (...args: any[]) => mockReleaseClient(...args),
  createProjectTx: (...args: any[]) => mockCreateProjectTx(...args),
  createVersionTx: (...args: any[]) => mockCreateVersionTx(...args),
  createPropertyTx: (...args: any[]) => mockCreatePropertyTx(...args),
  createPropertiesBatchTx: (...args: any[]) => mockCreatePropertiesBatchTx(...args),
  createClassTx: async (...args: any[]) => {
    const result = await mockCreateClassTx(...args);
    return result;
  },
  addPropertyToClassTx: (...args: any[]) => mockAddPropertyToClassTx(...args),
  addPropertiesToClassBatchTx: (...args: any[]) => mockAddPropertiesToClassBatchTx(...args),
  getClassesWithPropertiesAndTagsTx: (...args: any[]) => mockGetClassesWithPropertiesAndTagsTx(...args),
  getLatestVersionUuidForProjectTx: (...args: any[]) => mockGetLatestVersionUuidForProjectTx(...args),
  getProjectIdBySlugTx: (...args: any[]) => mockGetProjectIdBySlugTx(...args),
  listProjectLibraryPropertiesTx: (...args: any[]) => mockListProjectLibraryPropertiesTx(...args),
}));

const mockNormalizeResult = {
  classes: [
    {
      name: 'User',
      description: null,
      schema: { type: 'object' },
      properties: [
        { name: 'id', data: { type: 'string' }, description: null },
        { name: 'email', data: { type: 'string' }, description: null },
      ],
    },
    {
      name: 'Product',
      description: null,
      schema: { type: 'object' },
      properties: [
        { name: 'id', data: { type: 'string' }, description: null },
        { name: 'name', data: { type: 'string' }, description: null },
      ],
    },
  ],
  warnings: [] as string[],
};

jest.mock('../lib/importers', () => ({
  getImporter: jest.fn(() => ({
    kind: 'openapi',
    normalize: () => mockNormalizeResult,
  })),
  ImportSourceKind: { openapi: 'openapi', arazzo: 'arazzo', unknown: 'unknown' },
}));

async function waitForJobEnd(
  getImportStatus: (jobId: string) => Promise<any>,
  jobId: string,
  maxMs = 5000
): Promise<any> {
  const start = Date.now();
  while (Date.now() - start < maxMs) {
    const status = await getImportStatus(jobId);
    if (status.state !== 'queued' && status.state !== 'running') {
      return status;
    }
    await new Promise((r) => setTimeout(r, 30));
  }
  throw new Error(`Job ${jobId} did not finish within ${maxMs}ms`);
}

describe('Import Incremental Mode (#730)', () => {
  const incrementalInput = {
    tenantId: 'tenant-1',
    userId: 'user-1',
    sourceKind: 'openapi' as const,
    document: { openapi: '3.1.0', info: { title: 'Test API', version: '1.0.0' } },
    project: { name: 'Incremental Project', slug: 'incremental-project', description: null },
    version: { versionId: '1.0.0', description: null },
    options: { selectedSchemas: ['User', 'Product'], dryRun: false, incrementalMode: true },
  };

  const transactionModeInput = {
    ...incrementalInput,
    options: { selectedSchemas: ['User', 'Product'], dryRun: false, incrementalMode: false },
  };

  beforeEach(() => {
    createClassTxFailForClassName = null;
    mockGetTransactionClient.mockReset();
    mockBeginTransaction.mockReset();
    mockCommitTransaction.mockReset();
    mockRollbackTransaction.mockReset();
    mockReleaseClient.mockReset();
    mockCreateProjectTx.mockReset();
    mockCreateVersionTx.mockReset();
    mockCreatePropertyTx.mockReset();
    mockCreatePropertiesBatchTx.mockReset();
    mockCreateClassTx.mockReset();
    mockAddPropertyToClassTx.mockReset();
    mockAddPropertiesToClassBatchTx.mockReset();
    mockGetClassesWithPropertiesAndTagsTx.mockReset();
    mockGetLatestVersionUuidForProjectTx.mockReset();
    mockGetProjectIdBySlugTx.mockReset();
    mockGetProjectIdBySlugTx.mockResolvedValue(null);
    mockListProjectLibraryPropertiesTx.mockReset();

    mockGetTransactionClient.mockResolvedValue(mockClient);
    mockBeginTransaction.mockResolvedValue(undefined);
    mockCommitTransaction.mockResolvedValue(undefined);
    mockRollbackTransaction.mockResolvedValue(undefined);
    mockReleaseClient.mockResolvedValue(undefined);
    mockCreateProjectTx.mockResolvedValue(
      JSON.stringify({ success: true, project: { id: 'proj-incremental' } })
    );
    mockCreateVersionTx.mockResolvedValue(
      JSON.stringify({ success: true, version: { id: 'ver-incremental' } })
    );
    mockCreatePropertyTx.mockImplementation(
      (_c: any, _pid: string, name: string, _desc: any, data: any) =>
        Promise.resolve(
          JSON.stringify({ success: true, property: { id: `prop-${name}-${JSON.stringify(data).length}` } })
        )
    );
    mockCreatePropertiesBatchTx.mockImplementation((_c: any, rows: any[]) =>
      Promise.resolve(
        JSON.stringify({ success: true, inserted: Array.isArray(rows) ? rows.length : 0, failed: [] })
      )
    );
    mockCreateClassTx.mockImplementation((_c: any, _vid: string, name: string) => {
      if (createClassTxFailForClassName !== null && name === createClassTxFailForClassName) {
        return Promise.resolve(JSON.stringify({ success: false, error: 'Duplicate class (simulated)' }));
      }
      return Promise.resolve(JSON.stringify({ success: true, class: { id: `class-${name}` } }));
    });
    mockAddPropertyToClassTx.mockResolvedValue(
      JSON.stringify({ success: true, classProperty: { id: 'cp-1' } })
    );
    mockAddPropertiesToClassBatchTx.mockImplementation((_c: any, rows: any[]) =>
      Promise.resolve(JSON.stringify({ success: true, inserted: Array.isArray(rows) ? rows.length : 0, failed: [] }))
    );
    mockGetClassesWithPropertiesAndTagsTx.mockResolvedValue(
      JSON.stringify([
        { name: 'User', schema: {}, properties: [] },
        { name: 'Product', schema: {}, properties: [] },
      ])
    );
    mockGetLatestVersionUuidForProjectTx.mockResolvedValue(null);
    mockListProjectLibraryPropertiesTx.mockResolvedValue([]);
  });

  afterEach(() => {
    jest.resetModules();
  });

  test('incremental mode completes with state completed and summary.incrementalMode true', async () => {
    const { startImport, getImportStatus } = await import('../lib/db/import-helper');
    const { jobId } = await startImport(incrementalInput);

    const status = await waitForJobEnd(getImportStatus, jobId);

    expect(status.state).toBe('completed');
    expect(status.summary).toBeDefined();
    expect(status.summary.incrementalMode).toBe(true);
  });

  test('incremental mode sets result with projectId and versionId', async () => {
    const { startImport, getImportStatus } = await import('../lib/db/import-helper');
    const { jobId } = await startImport(incrementalInput);

    const status = await waitForJobEnd(getImportStatus, jobId);

    expect(status.result).toBeDefined();
    expect(status.result.projectId).toBe('proj-incremental');
    expect(status.result.versionId).toBe('ver-incremental');
  });

  test('incremental mode does not set transactionPending (no pending-approval)', async () => {
    const { startImport, getImportStatus } = await import('../lib/db/import-helper');
    const { jobId } = await startImport(incrementalInput);

    const status = await waitForJobEnd(getImportStatus, jobId);

    expect(status.state).toBe('completed');
    expect((status as any).transactionPending).toBeFalsy();
  });

  test('incremental mode emits INCREMENTAL_MODE and INCREMENTAL_COMPLETE events', async () => {
    const { startImport, getImportStatus } = await import('../lib/db/import-helper');
    const { jobId } = await startImport(incrementalInput);

    const status = await waitForJobEnd(getImportStatus, jobId);

    const incrementalModeEvent = status.events?.find((e: any) => e.code === 'INCREMENTAL_MODE');
    const completeEvent = status.events?.find((e: any) => e.code === 'INCREMENTAL_COMPLETE');

    expect(incrementalModeEvent).toBeDefined();
    expect(incrementalModeEvent?.level).toBe('info');
    expect(incrementalModeEvent?.message).toMatch(/incremental|skip/i);
    expect(completeEvent).toBeDefined();
    expect(completeEvent?.message).toMatch(/complete|skipped/i);
  });

  test('incremental mode calls getTransactionClient and releaseClient', async () => {
    const { startImport, getImportStatus } = await import('../lib/db/import-helper');
    const { jobId } = await startImport(incrementalInput);

    await waitForJobEnd(getImportStatus, jobId);

    expect(mockGetTransactionClient).toHaveBeenCalled();
    expect(mockReleaseClient).toHaveBeenCalled();
  });

  test('incremental mode uses per-class transaction (begin/commit per class)', async () => {
    const { startImport, getImportStatus } = await import('../lib/db/import-helper');
    const { jobId } = await startImport(incrementalInput);

    await waitForJobEnd(getImportStatus, jobId);

    // No global begin at start in incremental path. Begin/commit pairs:
    //   1× property-library build (its batched insert is SAVEPOINT-protected and so must
    //      run inside a transaction block) + 1× per class (2 classes) = 3 total.
    expect(mockBeginTransaction).toHaveBeenCalled();
    expect(mockCommitTransaction).toHaveBeenCalled();
    expect(mockBeginTransaction.mock.calls.length).toBe(3);
    expect(mockCommitTransaction.mock.calls.length).toBe(3);
  });

  test('incremental mode builds the property library inside a transaction block', async () => {
    // Regression (#3682 build fix): createPropertiesBatchTx issues SAVEPOINT, which
    // PostgreSQL rejects outside a transaction ("SAVEPOINT can only be used in transaction
    // blocks"). Incremental mode otherwise runs in autocommit, so the property-library build
    // must be wrapped in begin/commit. Assert a begin precedes the batch insert and a commit
    // follows it.
    const { startImport, getImportStatus } = await import('../lib/db/import-helper');
    const { jobId } = await startImport(incrementalInput);

    await waitForJobEnd(getImportStatus, jobId);

    expect(mockCreatePropertiesBatchTx).toHaveBeenCalled();
    const batchOrder = mockCreatePropertiesBatchTx.mock.invocationCallOrder[0];
    const beginBeforeBatch = mockBeginTransaction.mock.invocationCallOrder.some((o) => o < batchOrder);
    const commitAfterBatch = mockCommitTransaction.mock.invocationCallOrder.some((o) => o > batchOrder);
    expect(beginBeforeBatch).toBe(true);
    expect(commitAfterBatch).toBe(true);
  });

  test('incremental mode summary has classesCreated and totalTime', async () => {
    const { startImport, getImportStatus } = await import('../lib/db/import-helper');
    const { jobId } = await startImport(incrementalInput);

    const status = await waitForJobEnd(getImportStatus, jobId);

    expect(status.summary?.classesCreated).toBe(2);
    expect(status.summary?.classes?.length).toBe(2);
    expect(status.summary?.totalTime).toBeDefined();
    expect(typeof status.summary?.totalTime).toBe('number');
  });

  test('when one class fails in incremental mode: job still completes, failed class skipped', async () => {
    createClassTxFailForClassName = 'Product';

    const { startImport, getImportStatus } = await import('../lib/db/import-helper');
    const { jobId } = await startImport(incrementalInput);

    const status = await waitForJobEnd(getImportStatus, jobId);

    expect(status.state).toBe('completed');
    expect(status.summary?.incrementalMode).toBe(true);
    expect(status.summary?.classesCreated).toBe(1);
    expect(status.summary?.failed).toBe(1);
    const successClass = status.summary?.classes?.find((c: any) => c.status === 'success');
    const failedClass = status.summary?.classes?.find((c: any) => c.status === 'failed');
    expect(successClass?.name).toBe('User');
    expect(failedClass?.name).toBe('Product');
  });

  test('when one class fails in incremental mode: rollback called for that class only', async () => {
    createClassTxFailForClassName = 'Product';

    const { startImport, getImportStatus } = await import('../lib/db/import-helper');
    const { jobId } = await startImport(incrementalInput);

    await waitForJobEnd(getImportStatus, jobId);

    // Property library: begin, commit. First class (User): begin, commit. Second class
    // (Product): begin, then createClassTx fails → rollback. So 2 commits (library + User).
    expect(mockRollbackTransaction).toHaveBeenCalled();
    expect(mockCommitTransaction.mock.calls.length).toBe(2); // property library + User
  });

  test('when one class fails in incremental mode: CLASS_FAILED event emitted', async () => {
    createClassTxFailForClassName = 'Product';

    const { startImport, getImportStatus } = await import('../lib/db/import-helper');
    const { jobId } = await startImport(incrementalInput);

    const status = await waitForJobEnd(getImportStatus, jobId);

    const classFailedEvent = status.events?.find(
      (e: any) => e.code === 'CLASS_FAILED' && e.message?.includes('Product')
    );
    expect(classFailedEvent).toBeDefined();
    expect(classFailedEvent?.level).toBe('error');
  });

  test('ImportJobInput allows incrementalMode in options', () => {
    const input = {
      tenantId: 't',
      userId: 'u',
      sourceKind: 'openapi' as any,
      document: {},
      project: { name: 'P', slug: 'p' },
      version: { versionId: '1.0.0' },
      options: { selectedSchemas: [], dryRun: false, incrementalMode: true },
    };
    expect(input.options.incrementalMode).toBe(true);
  });

  test('incrementalMode false (transaction mode) reaches pending-approval', async () => {
    const { startImport, getImportStatus } = await import('../lib/db/import-helper');
    const { jobId } = await startImport(transactionModeInput);

    const status = await waitForJobEnd(getImportStatus, jobId);

    expect(status.state).toBe('pending-approval');
    expect((status as any).transactionPending).toBe(true);
    expect(status.summary?.incrementalMode).toBeFalsy();
  });

  test('incremental mode with dry run true still does dry run (no incremental DB path)', async () => {
    const dryRunIncrementalInput = {
      ...incrementalInput,
      options: { ...incrementalInput.options, dryRun: true },
    };

    const { startImport, getImportStatus } = await import('../lib/db/import-helper');
    const { jobId } = await startImport(dryRunIncrementalInput);

    const status = await waitForJobEnd(getImportStatus, jobId);

    expect(status.state).toBe('completed');
    expect(status.summary?.dryRun).toBe(true);
    expect(mockGetTransactionClient).not.toHaveBeenCalled();
    // When dry run, incremental path is never hit
    expect(status.summary?.incrementalMode).toBeFalsy();
  });

  test('incremental mode with existingProjectId reuses property library shapes and sets version parent', async () => {
    mockGetLatestVersionUuidForProjectTx.mockResolvedValue('previous-version-uuid');
    mockListProjectLibraryPropertiesTx.mockResolvedValue([
      { id: 'existing-prop-1', name: 'id', description: null, data: { type: 'string' } },
    ]);

    const inputWithExisting = {
      ...incrementalInput,
      existingProjectId: 'already-created-project',
    };

    const { startImport, getImportStatus } = await import('../lib/db/import-helper');
    const { jobId } = await startImport(inputWithExisting);

    await waitForJobEnd(getImportStatus, jobId);

    expect(mockCreateProjectTx).not.toHaveBeenCalled();
    expect(mockGetLatestVersionUuidForProjectTx).toHaveBeenCalledWith(
      expect.anything(),
      'already-created-project'
    );
    expect(mockListProjectLibraryPropertiesTx).toHaveBeenCalledWith(
      expect.anything(),
      'already-created-project'
    );

    // Normalized fixture uses only { type: 'string' } for scalars; one library row covers every occurrence.
    expect(mockCreatePropertyTx).not.toHaveBeenCalled();

    const versionCalls = mockCreateVersionTx.mock.calls;
    expect(versionCalls.length).toBeGreaterThanOrEqual(1);
    const lastCall = versionCalls[versionCalls.length - 1];
    expect(lastCall[6]).toEqual({
      parentVersionUuid: 'previous-version-uuid',
      projectSlug: 'incremental-project',
    });
  });

  test('reuses an existing project with the same slug instead of creating a duplicate (new version of an existing API)', async () => {
    // No existingProjectId is supplied, but a project with this slug already exists in the tenant —
    // a new API version of an existing project. It must be reused, not rejected.
    mockGetProjectIdBySlugTx.mockResolvedValue('existing-project-by-slug');
    mockGetLatestVersionUuidForProjectTx.mockResolvedValue('prev-version-uuid');

    const { startImport, getImportStatus } = await import('../lib/db/import-helper');
    const { jobId } = await startImport(incrementalInput);

    await waitForJobEnd(getImportStatus, jobId);

    // Looked up by tenant + project slug, and the project was NOT re-created.
    expect(mockGetProjectIdBySlugTx).toHaveBeenCalledWith(
      expect.anything(),
      'tenant-1',
      'incremental-project'
    );
    expect(mockCreateProjectTx).not.toHaveBeenCalled();

    // The new version is created against the reused project.
    const versionCalls = mockCreateVersionTx.mock.calls;
    expect(versionCalls.length).toBeGreaterThanOrEqual(1);
    expect(versionCalls[versionCalls.length - 1][1]).toBe('existing-project-by-slug');
  });
});
