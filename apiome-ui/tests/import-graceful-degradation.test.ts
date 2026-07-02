/**
 * Import Graceful Degradation Tests (#733)
 *
 * Unit tests for "continue on non-critical errors" during import execution:
 * - Property link failure: addPropertyToClassTx fails → emit PROPERTY_LINK_FAILED warn, continue, reach pending-approval
 * - Verification failure: verification mismatches → do not throw, emit VERIFY_MISMATCHES warn, reach pending-approval
 */

import { describe, test, expect, beforeEach, afterEach, jest } from '@jest/globals';

// Track addPropertyToClassTx call count for "fail on Nth call" behavior
let addPropertyToClassTxCallCount = 0;
let addPropertyToClassTxFailOnCall: number | null = null;
// When set, the batched property insert reports this property name as a per-row failure
// (graceful degradation): the rest of the class still imports.
let batchFailForPropertyName: string | null = null;

// Control getClassesWithPropertiesAndTagsTx response for verification tests
let getClassesWithPropertiesAndTagsTxReturnsMismatch = false;

const mockClient = { query: jest.fn(), release: jest.fn() };

jest.mock('../lib/db/import-transaction', () => ({
  getTransactionClient: jest.fn(() => Promise.resolve(mockClient)),
  beginTransaction: jest.fn(() => Promise.resolve()),
  commitTransaction: jest.fn(() => Promise.resolve()),
  rollbackTransaction: jest.fn(() => Promise.resolve()),
  releaseClient: jest.fn(() => Promise.resolve()),
  createProjectTx: jest.fn(() =>
    Promise.resolve(JSON.stringify({ success: true, project: { id: 'proj-1' } }))
  ),
  createVersionTx: jest.fn(() =>
    Promise.resolve(JSON.stringify({ success: true, version: { id: 'ver-1' } }))
  ),
  createPropertyTx: jest.fn((_client: any, _projectId: string, _name: string, _desc: any, data: any) => {
    const id = 'prop-' + JSON.stringify(data).length;
    return Promise.resolve(JSON.stringify({ success: true, property: { id } }));
  }),
  createPropertiesBatchTx: jest.fn((_client: any, rows: any[]) =>
    Promise.resolve(
      JSON.stringify({ success: true, inserted: Array.isArray(rows) ? rows.length : 0, failed: [] })
    )
  ),
  createClassTx: jest.fn(() =>
    Promise.resolve(JSON.stringify({ success: true, class: { id: 'class-1' } }))
  ),
  addPropertyToClassTx: jest.fn(async () => {
    addPropertyToClassTxCallCount++;
    if (addPropertyToClassTxFailOnCall !== null && addPropertyToClassTxCallCount === addPropertyToClassTxFailOnCall) {
      return Promise.resolve(
        JSON.stringify({ success: false, error: 'Constraint violation (simulated)' })
      );
    }
    return Promise.resolve(
      JSON.stringify({ success: true, classProperty: { id: 'cp-' + addPropertyToClassTxCallCount } })
    );
  }),
  addPropertiesToClassBatchTx: jest.fn(async (_client: any, rows: any[]) => {
    const list = Array.isArray(rows) ? rows : [];
    const failed = batchFailForPropertyName
      ? list.filter((r) => r.name === batchFailForPropertyName).map((r) => ({ name: r.name, error: 'Constraint violation (simulated)' }))
      : [];
    return Promise.resolve(
      JSON.stringify({ success: true, inserted: list.length - failed.length, failed })
    );
  }),
  getClassesWithPropertiesAndTagsTx: jest.fn(async () => {
    if (getClassesWithPropertiesAndTagsTxReturnsMismatch) {
      return Promise.resolve(JSON.stringify([])); // No classes → verification will find missing_class
    }
    return Promise.resolve(
      JSON.stringify([
        {
          name: 'TestClass',
          schema: {},
          properties: [
            { id: 'p1', name: 'id', data: { type: 'string' }, children: [] },
            { id: 'p2', name: 'name', data: { type: 'number' }, children: [] }
          ]
        }
      ])
    );
  }),
  getLatestVersionUuidForProjectTx: jest.fn(() => Promise.resolve(null)),
  getProjectIdBySlugTx: jest.fn(() => Promise.resolve(null)),
  listProjectLibraryPropertiesTx: jest.fn(() => Promise.resolve([])),
}));

// Normalized class: two properties with different types so we get two addPropertyToClassTx calls
const mockNormalizeResult = {
  classes: [
    {
      name: 'TestClass',
      description: null,
      schema: { type: 'object' },
      properties: [
        { name: 'id', data: { type: 'string' }, description: null },
        { name: 'count', data: { type: 'number' }, description: null }
      ]
    }
  ],
  warnings: [] as string[]
};

jest.mock('../lib/importers', () => ({
  getImporter: jest.fn(() => ({
    kind: 'openapi',
    normalize: () => mockNormalizeResult
  })),
  ImportSourceKind: { openapi: 'openapi', arazzo: 'arazzo', unknown: 'unknown' }
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

describe('Import Graceful Degradation (#733)', () => {
  const validInput = {
    tenantId: 'tenant-1',
    userId: 'user-1',
    sourceKind: 'openapi' as const,
    document: { openapi: '3.1.0' },
    project: { name: 'Test', slug: 'test', description: null },
    version: { versionId: '1.0.0', description: null },
    options: { selectedSchemas: [] }
  };

  beforeEach(() => {
    addPropertyToClassTxCallCount = 0;
    addPropertyToClassTxFailOnCall = null;
    batchFailForPropertyName = null;
    getClassesWithPropertiesAndTagsTxReturnsMismatch = false;
    mockClient.query.mockReset();
    mockClient.release.mockReset();
  });

  afterEach(() => {
    jest.resetModules();
  });

  test('when addPropertyToClassTx fails for one property: emits PROPERTY_LINK_FAILED warn and reaches pending-approval', async () => {
    batchFailForPropertyName = 'count'; // The batched insert reports one property as failed

    const { startImport, getImportStatus } = await import('../lib/db/import-helper');
    const { jobId } = await startImport(validInput);

    const status = await waitForJobEnd(getImportStatus, jobId);

    expect(status.state).toBe('pending-approval');
    const propertyLinkFailed = status.events?.find(
      (e: any) => e.code === 'PROPERTY_LINK_FAILED' && e.level === 'warn'
    );
    expect(propertyLinkFailed).toBeDefined();
    expect(propertyLinkFailed?.message).toContain('Could not add property');
    expect(status.summary?.warnings).toBeGreaterThanOrEqual(1);
    expect(status.summary?.classesCreated).toBe(1);
  });

  test('when verification fails (mismatches): does not throw, emits VERIFY_MISMATCHES warn and reaches pending-approval', async () => {
    getClassesWithPropertiesAndTagsTxReturnsMismatch = true; // DB "returns" no classes → verification finds missing_class

    const { startImport, getImportStatus } = await import('../lib/db/import-helper');
    const { jobId } = await startImport(validInput);

    const status = await waitForJobEnd(getImportStatus, jobId);

    expect(status.state).toBe('pending-approval');
    const verifyMismatches = status.events?.filter((e: any) => e.code === 'VERIFY_MISMATCHES');
    expect(verifyMismatches?.length).toBeGreaterThanOrEqual(1);
    expect(verifyMismatches?.some((e: any) => e.level === 'warn')).toBe(true);
    expect(status.summary?.verification?.passed).toBe(false);
    expect(status.summary?.verification?.mismatches?.length).toBeGreaterThan(0);
    expect(status.result?.projectId).toBe('proj-1');
    expect(status.result?.versionId).toBe('ver-1');
  });

  test('when no non-critical errors: reaches pending-approval and completes without critical failure', async () => {
    const { startImport, getImportStatus } = await import('../lib/db/import-helper');
    const { jobId } = await startImport(validInput);

    const status = await waitForJobEnd(getImportStatus, jobId);

    expect(status.state).toBe('pending-approval');
    expect(status.events?.some((e: any) => e.code === 'PROPERTY_LINK_FAILED')).toBe(false);
    expect(status.summary?.classesCreated).toBe(1);
    expect(status.result?.projectId).toBeDefined();
    expect(status.result?.versionId).toBeDefined();
  });

  test('critical error (missing tenantId) throws and does not start job', async () => {
    const { startImport } = await import('../lib/db/import-helper');

    await expect(
      startImport({ ...validInput, tenantId: '' })
    ).rejects.toThrow('Tenant ID is required');
  });
});
