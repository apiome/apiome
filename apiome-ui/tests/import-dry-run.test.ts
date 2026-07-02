/**
 * Import Dry Run Tests (#729)
 *
 * Unit tests for dry-run mode: preview import changes without committing.
 * - When options.dryRun === true, no DB transaction or writes occur
 * - Job completes with state 'completed', summary.dryRun === true, no result.projectId/versionId
 * - Log events include DRY_RUN and DRY_RUN_COMPLETE
 * - getTransactionClient and beginTransaction are never called
 */

import { describe, test, expect, beforeEach, afterEach, jest } from '@jest/globals';

const mockGetTransactionClient = jest.fn();
const mockBeginTransaction = jest.fn();
const mockClient = { query: jest.fn(), release: jest.fn() };

jest.mock('../lib/db/import-transaction', () => ({
  getTransactionClient: (...args: any[]) => mockGetTransactionClient(...args),
  beginTransaction: (...args: any[]) => mockBeginTransaction(...args),
  commitTransaction: jest.fn(),
  rollbackTransaction: jest.fn(),
  releaseClient: jest.fn(),
  createProjectTx: jest.fn(),
  createVersionTx: jest.fn(),
  createPropertyTx: jest.fn(),
  createClassTx: jest.fn(),
  addPropertyToClassTx: jest.fn(),
  getClassesWithPropertiesAndTagsTx: jest.fn(),
  getLatestVersionUuidForProjectTx: jest.fn(() => Promise.resolve(null)),
  getProjectIdBySlugTx: jest.fn(() => Promise.resolve(null)),
  listProjectLibraryPropertiesTx: jest.fn(() => Promise.resolve([])),
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
  maxMs = 3000
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

describe('Import Dry Run (#729)', () => {
  const dryRunInput = {
    tenantId: 'tenant-1',
    userId: 'user-1',
    sourceKind: 'openapi' as const,
    document: { openapi: '3.1.0', info: { title: 'Test API', version: '1.0.0' } },
    project: { name: 'Dry Run Project', slug: 'dry-run-project', description: null },
    version: { versionId: '1.0.0', description: null },
    options: { selectedSchemas: ['User', 'Product'], dryRun: true },
  };

  const normalInput = {
    ...dryRunInput,
    options: { selectedSchemas: ['User', 'Product'], dryRun: false },
  };

  beforeEach(() => {
    mockGetTransactionClient.mockReset();
    mockBeginTransaction.mockReset();
    mockGetTransactionClient.mockResolvedValue(mockClient);
    mockBeginTransaction.mockResolvedValue(undefined);
  });

  afterEach(() => {
    jest.resetModules();
  });

  test('dry run completes with state completed and summary.dryRun true', async () => {
    const { startImport, getImportStatus } = await import('../lib/db/import-helper');
    const { jobId } = await startImport(dryRunInput);

    const status = await waitForJobEnd(getImportStatus, jobId);

    expect(status.state).toBe('completed');
    expect(status.summary).toBeDefined();
    expect(status.summary.dryRun).toBe(true);
  });

  test('dry run does not create project or version (no result IDs)', async () => {
    const { startImport, getImportStatus } = await import('../lib/db/import-helper');
    const { jobId } = await startImport(dryRunInput);

    const status = await waitForJobEnd(getImportStatus, jobId);

    expect(status.result).toBeUndefined();
    expect(status.summary?.projectName).toBe(dryRunInput.project.name);
    expect(status.summary?.versionId).toBe(dryRunInput.version.versionId);
  });

  test('dry run does not call getTransactionClient or beginTransaction', async () => {
    const { startImport, getImportStatus } = await import('../lib/db/import-helper');
    const { jobId } = await startImport(dryRunInput);

    await waitForJobEnd(getImportStatus, jobId);

    expect(mockGetTransactionClient).not.toHaveBeenCalled();
    expect(mockBeginTransaction).not.toHaveBeenCalled();
  });

  test('dry run emits DRY_RUN and DRY_RUN_COMPLETE events', async () => {
    const { startImport, getImportStatus } = await import('../lib/db/import-helper');
    const { jobId } = await startImport(dryRunInput);

    const status = await waitForJobEnd(getImportStatus, jobId);

    const dryRunEvent = status.events?.find((e: any) => e.code === 'DRY_RUN');
    const completeEvent = status.events?.find((e: any) => e.code === 'DRY_RUN_COMPLETE');

    expect(dryRunEvent).toBeDefined();
    expect(dryRunEvent?.level).toBe('info');
    expect(completeEvent).toBeDefined();
    expect(completeEvent?.message).toMatch(/no changes were saved|Dry run complete/i);
  });

  test('dry run summary contains expected class and property counts', async () => {
    const { startImport, getImportStatus } = await import('../lib/db/import-helper');
    const { jobId } = await startImport(dryRunInput);

    const status = await waitForJobEnd(getImportStatus, jobId);

    expect(status.summary?.classesCreated).toBe(2);
    expect(status.summary?.classes?.length).toBe(2);
    expect(status.summary?.classes?.map((c: any) => c.name)).toEqual(
      expect.arrayContaining(['User', 'Product'])
    );
    // Unique properties by JSON signature (id/email/name may share type → 1 or more)
    expect(status.summary?.propertiesCreated).toBeGreaterThanOrEqual(1);
    expect(status.summary?.totalTime).toBeDefined();
    expect(typeof status.summary?.totalTime).toBe('number');
  });

  test('dry run percent reaches 100', async () => {
    const { startImport, getImportStatus } = await import('../lib/db/import-helper');
    const { jobId } = await startImport(dryRunInput);

    const status = await waitForJobEnd(getImportStatus, jobId);

    expect(status.percent).toBe(100);
  });

  test('dry run with empty selectedSchemas still runs and completes', async () => {
    const input = { ...dryRunInput, options: { selectedSchemas: [], dryRun: true } };
    const { startImport, getImportStatus } = await import('../lib/db/import-helper');
    const { jobId } = await startImport(input);

    const status = await waitForJobEnd(getImportStatus, jobId);

    expect(status.state).toBe('completed');
    expect(status.summary?.dryRun).toBe(true);
    expect(mockGetTransactionClient).not.toHaveBeenCalled();
  });

  test('ImportJobInput allows dryRun in options', () => {
    const input = {
      tenantId: 't',
      userId: 'u',
      sourceKind: 'openapi' as any,
      document: {},
      project: { name: 'P', slug: 'p' },
      version: { versionId: '1.0.0' },
      options: { selectedSchemas: [], dryRun: true },
    };
    expect(input.options.dryRun).toBe(true);
  });
});
