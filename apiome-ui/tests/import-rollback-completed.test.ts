/**
 * Import Rollback Completed Tests (#735)
 *
 * Tests for rollbackCompletedImport: undo a completed import by removing
 * the created project and all its data. Only allowed when state === 'completed'.
 */

import { describe, test, expect, beforeEach, afterEach, jest } from '@jest/globals';

const mockPermanentDeleteProject = jest.fn();
const mockClient = { query: jest.fn(), release: jest.fn() };

jest.mock('../lib/db/helper', () => ({
  permanentDeleteProject: (...args: any[]) => mockPermanentDeleteProject(...args),
}));

jest.mock('../lib/db/import-transaction', () => ({
  getTransactionClient: jest.fn(() => Promise.resolve(mockClient)),
  beginTransaction: jest.fn(() => Promise.resolve()),
  commitTransaction: jest.fn(() => Promise.resolve()),
  rollbackTransaction: jest.fn(() => Promise.resolve()),
  releaseClient: jest.fn(() => Promise.resolve()),
  createProjectTx: jest.fn(() =>
    Promise.resolve(JSON.stringify({ success: true, project: { id: 'proj-rollback-test' } }))
  ),
  createVersionTx: jest.fn(() =>
    Promise.resolve(JSON.stringify({ success: true, version: { id: 'ver-rollback-test' } }))
  ),
  createPropertyTx: jest.fn((_client: any, _projectId: string, _name: string, _desc: any, data: any) =>
    Promise.resolve(JSON.stringify({ success: true, property: { id: 'prop-' + JSON.stringify(data).length } }))
  ),
  createPropertiesBatchTx: jest.fn((_c: any, rows: any[]) =>
    Promise.resolve(JSON.stringify({ success: true, inserted: Array.isArray(rows) ? rows.length : 0, failed: [] }))
  ),
  createClassTx: jest.fn(() =>
    Promise.resolve(JSON.stringify({ success: true, class: { id: 'class-1' } }))
  ),
  addPropertyToClassTx: jest.fn(() =>
    Promise.resolve(JSON.stringify({ success: true, classProperty: { id: 'cp-1' } }))
  ),
  addPropertiesToClassBatchTx: jest.fn((_c: any, rows: any[]) =>
    Promise.resolve(JSON.stringify({ success: true, inserted: Array.isArray(rows) ? rows.length : 0, failed: [] }))
  ),
  getClassesWithPropertiesAndTagsTx: jest.fn(() =>
    Promise.resolve(
      JSON.stringify([
        {
          name: 'TestClass',
          schema: {},
          properties: [
            { id: 'p1', name: 'id', data: { type: 'string' }, children: [] },
            { id: 'p2', name: 'name', data: { type: 'number' }, children: [] },
          ],
        },
      ])
    )
  ),
  getLatestVersionUuidForProjectTx: jest.fn(() => Promise.resolve(null)),
  getProjectIdBySlugTx: jest.fn(() => Promise.resolve(null)),
  listProjectLibraryPropertiesTx: jest.fn(() => Promise.resolve([])),
}));

const mockNormalizeResult = {
  classes: [
    {
      name: 'TestClass',
      description: null,
      schema: { type: 'object' },
      properties: [
        { name: 'id', data: { type: 'string' }, description: null },
        { name: 'count', data: { type: 'number' }, description: null },
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
    await new Promise((r) => setTimeout(r, 50));
  }
  throw new Error(`Job ${jobId} did not finish within ${maxMs}ms`);
}

describe('rollbackCompletedImport (#735)', () => {
  const validInput = {
    tenantId: 'tenant-1',
    userId: 'user-1',
    sourceKind: 'openapi' as const,
    document: { openapi: '3.1.0' },
    project: { name: 'Test', slug: 'test', description: null },
    version: { versionId: '1.0.0', description: null },
    options: { selectedSchemas: [] },
  };

  beforeEach(() => {
    mockPermanentDeleteProject.mockReset();
    mockPermanentDeleteProject.mockResolvedValue(JSON.stringify({ success: true }));
    mockClient.query.mockClear();
    mockClient.release.mockClear();
  });

  afterEach(() => {
    jest.resetModules();
  });

  test('returns Job not found for unknown jobId', async () => {
    const { rollbackCompletedImport } = await import('../lib/db/import-helper');

    const result = await rollbackCompletedImport('nonexistent-job-id');

    expect(result.success).toBe(false);
    expect(result.error).toBe('Job not found');
    expect(mockPermanentDeleteProject).not.toHaveBeenCalled();
  });

  test('returns error when job is pending-approval (not completed)', async () => {
    const { startImport, getImportStatus, rollbackCompletedImport } = await import('../lib/db/import-helper');

    const { jobId } = await startImport(validInput);
    const status = await waitForJobEnd(getImportStatus, jobId);
    expect(status.state).toBe('pending-approval');

    const result = await rollbackCompletedImport(jobId);

    expect(result.success).toBe(false);
    expect(result.error).toContain('only allowed when the import has been committed');
    expect(result.error).toContain('pending-approval');
    expect(mockPermanentDeleteProject).not.toHaveBeenCalled();
  });

  test('calls permanentDeleteProject with projectId and sets state to rolled-back when job is completed', async () => {
    const { startImport, getImportStatus, commitImport, rollbackCompletedImport } = await import(
      '../lib/db/import-helper'
    );

    const { jobId } = await startImport(validInput);
    const status = await waitForJobEnd(getImportStatus, jobId);
    expect(status.state).toBe('pending-approval');
    expect(status.result?.projectId).toBe('proj-rollback-test');

    const commitResult = await commitImport(jobId);
    expect(commitResult.success).toBe(true);

    const rollbackResult = await rollbackCompletedImport(jobId);

    expect(rollbackResult.success).toBe(true);
    expect(mockPermanentDeleteProject).toHaveBeenCalledTimes(1);
    expect(mockPermanentDeleteProject).toHaveBeenCalledWith('proj-rollback-test');

    const afterStatus = await getImportStatus(jobId);
    expect(afterStatus.state).toBe('rolled-back');
    expect(afterStatus.result).toBeUndefined();
  });

  test('emits ROLLBACK_STARTED and ROLLED_BACK events on success', async () => {
    const { startImport, getImportStatus, commitImport, rollbackCompletedImport } = await import(
      '../lib/db/import-helper'
    );

    const { jobId } = await startImport(validInput);
    await waitForJobEnd(getImportStatus, jobId);
    await commitImport(jobId);
    await rollbackCompletedImport(jobId);

    const status = await getImportStatus(jobId);
    const codes = status.events.map((e: any) => e.code);
    expect(codes).toContain('ROLLBACK_STARTED');
    expect(codes).toContain('ROLLED_BACK');
  });

  test('returns error when permanentDeleteProject returns success: false', async () => {
    mockPermanentDeleteProject.mockResolvedValue(
      JSON.stringify({ success: false, error: 'Project in use' })
    );

    const { startImport, getImportStatus, commitImport, rollbackCompletedImport } = await import(
      '../lib/db/import-helper'
    );

    const { jobId } = await startImport(validInput);
    await waitForJobEnd(getImportStatus, jobId);
    await commitImport(jobId);

    const result = await rollbackCompletedImport(jobId);

    expect(result.success).toBe(false);
    expect(result.error).toBe('Project in use');
    expect(mockPermanentDeleteProject).toHaveBeenCalledWith('proj-rollback-test');

    const status = await getImportStatus(jobId);
    expect(status.state).toBe('completed');
    const rollbackFailed = status.events?.find((e: any) => e.code === 'ROLLBACK_FAILED');
    expect(rollbackFailed).toBeDefined();
    expect(rollbackFailed?.level).toBe('error');
  });

  test('returns error when permanentDeleteProject throws', async () => {
    mockPermanentDeleteProject.mockRejectedValue(new Error('Database connection lost'));

    const { startImport, getImportStatus, commitImport, rollbackCompletedImport } = await import(
      '../lib/db/import-helper'
    );

    const { jobId } = await startImport(validInput);
    await waitForJobEnd(getImportStatus, jobId);
    await commitImport(jobId);

    const result = await rollbackCompletedImport(jobId);

    expect(result.success).toBe(false);
    expect(result.error).toContain('Database connection lost');
    expect(mockPermanentDeleteProject).toHaveBeenCalledWith('proj-rollback-test');
  });

  test('handles permanentDeleteProject returning object (not JSON string)', async () => {
    mockPermanentDeleteProject.mockResolvedValue({ success: true });

    const { startImport, getImportStatus, commitImport, rollbackCompletedImport } = await import(
      '../lib/db/import-helper'
    );

    const { jobId } = await startImport(validInput);
    await waitForJobEnd(getImportStatus, jobId);
    await commitImport(jobId);

    const result = await rollbackCompletedImport(jobId);

    expect(result.success).toBe(true);
    expect(mockPermanentDeleteProject).toHaveBeenCalledWith('proj-rollback-test');
  });
});
