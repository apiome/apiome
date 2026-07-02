/**
 * Import-time spec capture wiring tests (RAR-1.2, #3513)
 *
 * Verifies that a successful repository-sourced import persists the import spec
 * alongside the audit row. Both the manual and the auto-import paths converge on
 * import-helper's post-success metric step, so driving one successful import
 * through startImport exercises the shared capture site.
 *
 * The repository-import-metrics module is mocked so we assert the capture call
 * and its payload (persisted spec == submitted spec) without a live database;
 * the SQL contract itself is covered by repository-import-spec-upsert.test.ts.
 */

import { describe, test, expect, beforeEach, afterEach, jest } from '@jest/globals';

const mockClient = { query: jest.fn(), release: jest.fn() };

jest.mock('../lib/db/import-transaction', () => ({
  getTransactionClient: jest.fn(() => Promise.resolve(mockClient)),
  beginTransaction: jest.fn(() => Promise.resolve()),
  commitTransaction: jest.fn(() => Promise.resolve()),
  rollbackTransaction: jest.fn(() => Promise.resolve()),
  releaseClient: jest.fn(() => Promise.resolve()),
  createProjectTx: jest.fn(() =>
    Promise.resolve(JSON.stringify({ success: true, project: { id: 'proj-capture' } }))
  ),
  createVersionTx: jest.fn(() =>
    Promise.resolve(JSON.stringify({ success: true, version: { id: 'ver-capture' } }))
  ),
  createPropertyTx: jest.fn(() =>
    Promise.resolve(JSON.stringify({ success: true, property: { id: 'prop-1' } }))
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
          name: 'Pet',
          schema: {},
          properties: [{ id: 'p1', name: 'id', data: { type: 'string' }, children: [] }],
        },
      ])
    )
  ),
  getLatestVersionUuidForProjectTx: jest.fn(() => Promise.resolve(null)),
  getProjectIdBySlugTx: jest.fn(() => Promise.resolve(null)),
  getVersionUuidForCatalogVersionLineTx: jest.fn(() => Promise.resolve(null)),
  listProjectLibraryPropertiesTx: jest.fn(() => Promise.resolve([])),
}));

jest.mock('../lib/importers', () => ({
  getImporter: jest.fn(() => ({
    kind: 'openapi',
    normalize: () => ({
      classes: [
        {
          name: 'Pet',
          description: null,
          schema: { type: 'object' },
          properties: [{ name: 'id', data: { type: 'string' }, description: null }],
        },
      ],
      warnings: [] as string[],
    }),
  })),
  ImportSourceKind: { openapi: 'openapi', arazzo: 'arazzo', unknown: 'unknown' },
}));

const mockRecordTenantRepositoryImport = jest.fn(() => Promise.resolve(true));
const mockUpsertRepositoryImportSpec = jest.fn(() => Promise.resolve(true));

jest.mock('../lib/db/repository-import-metrics', () => ({
  recordTenantRepositoryImport: (...args: any[]) => mockRecordTenantRepositoryImport(...args),
  upsertRepositoryImportSpec: (...args: any[]) => mockUpsertRepositoryImportSpec(...args),
}));

async function waitForState(
  getImportStatus: (jobId: string) => Promise<any>,
  jobId: string,
  done: (state: string) => boolean,
  maxMs = 5000
): Promise<any> {
  const start = Date.now();
  while (Date.now() - start < maxMs) {
    const status = await getImportStatus(jobId);
    if (done(status.state)) {
      return status;
    }
    await new Promise((r) => setTimeout(r, 50));
  }
  throw new Error(`Job ${jobId} did not reach the expected state within ${maxMs}ms`);
}

/**
 * Drive an import to a terminal state. The default (single-transaction) path
 * pauses at `pending-approval`; commit it so the post-success metric/spec
 * capture runs, exactly as the UI does.
 */
async function runImportToCompletion(
  helper: typeof import('../lib/db/import-helper'),
  jobId: string
): Promise<any> {
  const settled = (s: string) =>
    s === 'pending-approval' || s === 'completed' || s === 'failed' || s === 'canceled';
  let status = await waitForState(helper.getImportStatus, jobId, settled);
  if (status.state === 'pending-approval') {
    await helper.commitImport(jobId);
    status = await waitForState(
      helper.getImportStatus,
      jobId,
      (s) => s === 'completed' || s === 'failed'
    );
  }
  return status;
}

const SUBMITTED_OPTIONS = {
  selectedSchemas: ['Pet'],
  dryRun: false,
  incrementalMode: false,
  applyNamingConvention: true,
  classNamingConvention: 'PascalCase' as const,
  propertyNamingConvention: 'snake_case' as const,
  autoLayout: true,
  createRelationships: true,
  skipDuplicateVersions: false,
};

function repositoryImportInput() {
  return {
    tenantId: 'tenant-1',
    userId: 'user-1',
    sourceKind: 'openapi' as const,
    document: { openapi: '3.1.0', info: { title: 'Petstore', version: '1.0.0' } },
    project: { name: 'Petstore', slug: 'petstore', description: null },
    version: { versionId: '1.0.0', description: null },
    options: SUBMITTED_OPTIONS,
    repositorySource: {
      repositoryId: 'repo-1',
      branch: 'main',
      path: 'specs/petstore.yaml',
      blobSha: 'abc123',
    },
  };
}

describe('Import-time spec capture (RAR-1.2, #3513)', () => {
  beforeEach(() => {
    mockClient.query.mockReset();
    mockClient.release.mockReset();
    mockRecordTenantRepositoryImport.mockClear();
    mockUpsertRepositoryImportSpec.mockClear();
  });

  afterEach(() => {
    jest.resetModules();
  });

  test('a successful repository import persists the submitted spec', async () => {
    const helper = await import('../lib/db/import-helper');
    const { jobId } = await helper.startImport(repositoryImportInput());

    const status = await runImportToCompletion(helper, jobId);
    expect(status.state).toBe('completed');

    expect(mockUpsertRepositoryImportSpec).toHaveBeenCalledTimes(1);
    const arg = mockUpsertRepositoryImportSpec.mock.calls[0][0] as any;
    expect(arg.tenantId).toBe('tenant-1');
    expect(arg.projectId).toBe('proj-capture');
    expect(arg.sourceKind).toBe('openapi');
    expect(arg.createdByUserId).toBe('user-1');
    expect(arg.repositorySource).toEqual({
      repositoryId: 'repo-1',
      branch: 'main',
      path: 'specs/petstore.yaml',
      blobSha: 'abc123',
    });
    // persisted spec == submitted spec
    expect(arg.options).toEqual(SUBMITTED_OPTIONS);
  });

  test('spec capture happens alongside the audit row', async () => {
    const helper = await import('../lib/db/import-helper');
    const { jobId } = await helper.startImport(repositoryImportInput());

    await runImportToCompletion(helper, jobId);

    expect(mockRecordTenantRepositoryImport).toHaveBeenCalledTimes(1);
    expect(mockUpsertRepositoryImportSpec).toHaveBeenCalledTimes(1);
  });

  test('a non-repository import does not attempt spec capture', async () => {
    const input = repositoryImportInput();
    delete (input as any).repositorySource;

    const helper = await import('../lib/db/import-helper');
    const { jobId } = await helper.startImport(input);

    const status = await runImportToCompletion(helper, jobId);
    expect(status.state).toBe('completed');
    expect(mockUpsertRepositoryImportSpec).not.toHaveBeenCalled();
  });

  test('the source descriptor (format/content-type) is forwarded to capture (RAR-1.3)', async () => {
    const input = repositoryImportInput();
    input.repositorySource = {
      ...input.repositorySource,
      formatOverride: 'swagger',
      contentType: 'application/json',
    } as typeof input.repositorySource;

    const helper = await import('../lib/db/import-helper');
    const { jobId } = await helper.startImport(input);

    const status = await runImportToCompletion(helper, jobId);
    expect(status.state).toBe('completed');

    expect(mockUpsertRepositoryImportSpec).toHaveBeenCalledTimes(1);
    const arg = mockUpsertRepositoryImportSpec.mock.calls[0][0] as any;
    expect(arg.formatOverride).toBe('swagger');
    expect(arg.contentType).toBe('application/json');
  });

  test('a missing source descriptor is captured as null (RAR-1.3)', async () => {
    const helper = await import('../lib/db/import-helper');
    const { jobId } = await helper.startImport(repositoryImportInput());

    await runImportToCompletion(helper, jobId);

    const arg = mockUpsertRepositoryImportSpec.mock.calls[0][0] as any;
    expect(arg.formatOverride).toBeNull();
    expect(arg.contentType).toBeNull();
  });

  test('a spec-capture failure does not fail the import', async () => {
    mockUpsertRepositoryImportSpec.mockRejectedValueOnce(new Error('db down') as never);

    const helper = await import('../lib/db/import-helper');
    const { jobId } = await helper.startImport(repositoryImportInput());

    const status = await runImportToCompletion(helper, jobId);
    expect(status.state).toBe('completed');
    expect(mockUpsertRepositoryImportSpec).toHaveBeenCalledTimes(1);
  });
});
