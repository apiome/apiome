/**
 * @jest-environment node
 *
 * The import job's class writing, verification and decisions after DBP-1.9 (#7192):
 * `lib/db/import-helper.ts` with the transaction layer and the staging store mocked.
 *
 * - every class and property is written by one call, class by class only when that fails;
 * - verification is a comparison in the database, and rows are read back only on a difference;
 * - a staged import is accepted, rejected or canceled without a held client.
 */

import { beforeEach, describe, expect, jest, test } from '@jest/globals';

/* eslint-disable @typescript-eslint/no-explicit-any, @typescript-eslint/no-unused-vars -- typed mock signatures */
const mockClient = { query: jest.fn(async (..._args: any[]) => ({ rows: [], rowCount: 0 })), release: jest.fn() };
const mockTx = {
  getTransactionClient: jest.fn(async () => mockClient),
  beginTransaction: jest.fn(async () => undefined),
  commitTransaction: jest.fn(async () => undefined),
  rollbackTransaction: jest.fn(async () => undefined),
  releaseClient: jest.fn(async () => undefined),
  createProjectTx: jest.fn(async (..._args: any[]) => JSON.stringify({ success: true, project: { id: 'proj-1' } })),
  createVersionTx: jest.fn(async (..._args: any[]) => JSON.stringify({ success: true, version: { id: 'ver-1' } })),
  createPropertiesBatchTx: jest.fn(async (_client: any, rows: any[]) =>
    JSON.stringify({ success: true, inserted: rows.length, failed: [] }),
  ),
  createClassTx: jest.fn(async (..._args: any[]) => JSON.stringify({ success: true, class: { id: 'class-x' } })),
  addPropertiesToClassBatchTx: jest.fn(async (_client: any, rows: any[]) =>
    JSON.stringify({ success: true, inserted: rows.length, failed: [] }),
  ),
  createClassesWithPropertiesBulkTx: jest.fn(async (..._args: any[]) => undefined),
  verifyImportCountsTx: jest.fn(async (..._args: any[]) => ({ mismatched: [] as string[], extra: [] as string[] })),
  getClassesWithPropertiesAndTagsTx: jest.fn(async (..._args: any[]) => JSON.stringify([])),
  getLatestVersionUuidForProjectTx: jest.fn(async () => null as string | null),
  getProjectIdBySlugTx: jest.fn(async () => null as string | null),
  listProjectLibraryPropertiesTx: jest.fn(async () => [] as any[]),
  listVersionLabelsForProjectTx: jest.fn(async () => [] as string[]),
  mergeProjectImportOpenApiFieldsTx: jest.fn(async (..._args: any[]) => JSON.stringify({ success: true })),
};
const mockStaging = {
  acceptStagedImportTx: jest.fn(async (..._args: any[]) => ({ ok: true, projectId: 'proj-1', projectCreated: true }) as any),
  discardStagedImport: jest.fn(async (..._args: any[]) => true),
  listRepositorySourcesTx: jest.fn(async () => []),
  writeStagedManifestTx: jest.fn(async (..._args: any[]) => undefined),
};
const mockNormalized = { classes: [] as any[], warnings: [] as string[] };

jest.mock('../lib/db/import-transaction', () => mockTx);
jest.mock('../lib/db/import-staging', () => mockStaging);
jest.mock('../lib/db/helper', () => ({ permanentDeleteProject: jest.fn(), getTenantById: jest.fn() }));
jest.mock('../lib/importers', () => ({
  getImporter: jest.fn(() => ({ kind: 'json-schema', normalize: () => mockNormalized })),
}));

import { cancelImport, commitImport, getImportStatus, rollbackImport, startImport } from '../lib/db/import-helper';

const INPUT = {
  tenantId: 'tenant-1',
  userId: 'user-1',
  sourceKind: 'json-schema',
  document: {},
  project: { name: 'Shop', slug: 'shop', description: 'A shop' },
  version: { versionId: '1.0.0' },
  options: { selectedSchemas: [] },
};

/** Two classes: a nested property tree, and a property with no library entry to link to. */
function classes(): any[] {
  return [
    {
      name: 'Order',
      description: 'An order',
      schema: { type: 'object', discriminator: { propertyName: 'kind' } },
      properties: [
        {
          name: 'address',
          data: { type: 'object' },
          children: [{ name: 'street', data: { type: 'string' } }],
        },
        { name: 'customer', data: { $ref: '#/components/schemas/Customer' } },
      ],
    },
    { name: 'Customer', properties: [{ name: 'email', data: { type: 'string', format: 'email' } }] },
  ];
}

/** Run an import to the point where it stops, and return its job and status. */
async function run(input: Record<string, unknown> = INPUT) {
  const { jobId } = await startImport(input as never);
  for (;;) {
    const status = await getImportStatus(jobId);
    if (status.state !== 'queued' && status.state !== 'running') return { jobId, status };
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
}

const codes = (status: { events: Array<{ code: string }> }) => status.events.map((e) => e.code);

beforeEach(() => {
  jest.clearAllMocks();
  jest.spyOn(console, 'error').mockImplementation(() => undefined);
  mockNormalized.classes = classes();
  mockTx.createClassesWithPropertiesBulkTx.mockImplementation(async () => undefined);
  mockTx.verifyImportCountsTx.mockImplementation(async () => ({ mismatched: [], extra: [] }));
  mockTx.getProjectIdBySlugTx.mockImplementation(async () => null);
  mockTx.listProjectLibraryPropertiesTx.mockImplementation(async () => []);
  mockStaging.acceptStagedImportTx.mockImplementation(async () => ({ ok: true, projectId: 'proj-1', projectCreated: true }));
  mockStaging.discardStagedImport.mockImplementation(async () => true);
});

describe('writing classes', () => {
  test('every class and property goes to the database in one call', async () => {
    const { status } = await run();
    expect(status.state).toBe('pending-approval');
    expect(mockTx.createClassesWithPropertiesBulkTx).toHaveBeenCalledTimes(1);
    expect(mockTx.createClassTx).not.toHaveBeenCalled();
    expect(mockTx.addPropertiesToClassBatchTx).not.toHaveBeenCalled();

    const [, classRows, propertyRows] = mockTx.createClassesWithPropertiesBulkTx.mock.calls[0] as any[];
    expect(classRows.map((c: any) => [c.name, c.versionId, c.description])).toEqual([
      ['Order', 'ver-1', 'An order'],
      ['Customer', 'ver-1', null],
    ]);
    // A class without a schema is stored as an object.
    expect(classRows[1].schema).toEqual({ type: 'object' });
    // Ids are assigned by the importer: a nested property names its parent, listed before it.
    const byName = new Map<string, any>(propertyRows.map((r: any) => [r.name, r]));
    expect(propertyRows.map((r: any) => r.name)).toEqual(['address', 'street', 'customer', 'email']);
    expect(byName.get('street').parentId).toBe(byName.get('address').id);
    expect(byName.get('address').classId).toBe(classRows[0].id);
    expect(byName.get('email').classId).toBe(classRows[1].id);
    // A reference has no library property; anything else links to one.
    expect(byName.get('customer').propertyId).toBeNull();
    expect(byName.get('street').propertyId).toEqual(expect.any(String));
  });

  test('the job log and summary still record each class', async () => {
    const { status } = await run();
    expect(status.summary?.classesCreated).toBe(2);
    expect(status.summary?.classes).toEqual([
      { name: 'Order', status: 'success' },
      { name: 'Customer', status: 'success' },
    ]);
    expect(status.events.filter((e) => e.code === 'CLASS_CREATED').map((e) => e.message)).toEqual([
      'Imported class: Order',
      'Imported class: Customer',
    ]);
  });

  test('the attempt runs inside a savepoint of the import transaction', async () => {
    await run();
    const statements = mockClient.query.mock.calls.map((call) => String(call[0]));
    expect(statements).toEqual(['SAVEPOINT imp_classes', 'RELEASE SAVEPOINT imp_classes']);
  });

  test('a property with no library entry is left out with its children, and reported', async () => {
    mockTx.createPropertiesBatchTx.mockImplementationOnce(async (_client: any, rows: any[]) =>
      JSON.stringify({
        success: true,
        inserted: rows.length - 1,
        failed: [{ name: 'address', error: 'A property with this name already exists in this project' }],
      }),
    );
    const { status } = await run();
    const [, , propertyRows] = mockTx.createClassesWithPropertiesBulkTx.mock.calls[0] as any[];
    expect(propertyRows.map((r: any) => r.name)).toEqual(['customer', 'email']);
    expect(codes(status)).toEqual(expect.arrayContaining(['PROPERTY_CREATE_WARN', 'SKIP_PROPERTY', 'SKIP_CHILDREN']));
    expect(status.state).toBe('pending-approval');
  });

  test('when the database rejects the one call, classes are written one at a time and a bad one is skipped', async () => {
    mockTx.createClassesWithPropertiesBulkTx.mockImplementation(async () => {
      throw new Error('duplicate key value violates unique constraint');
    });
    mockTx.createClassTx.mockImplementation(async (_client: any, _version: any, name: any) =>
      name === 'Customer'
        ? JSON.stringify({ success: false, error: 'A class with this name already exists in this version' })
        : JSON.stringify({ success: true, class: { id: 'class-order' } }),
    );
    const { status } = await run();

    expect(status.state).toBe('pending-approval');
    expect(codes(status)).toEqual(expect.arrayContaining(['CLASS_BULK_FALLBACK', 'CLASS_FAILED']));
    expect(status.summary?.classes).toEqual([
      { name: 'Order', status: 'success' },
      { name: 'Customer', status: 'failed' },
    ]);
    // The failed attempt and the failed class are undone with the savepoint; the rest is kept.
    const statements = mockClient.query.mock.calls.map((call) => String(call[0]));
    expect(statements).toEqual([
      'SAVEPOINT imp_classes',
      'ROLLBACK TO SAVEPOINT imp_classes',
      'SAVEPOINT imp_classes',
      'RELEASE SAVEPOINT imp_classes',
      'SAVEPOINT imp_classes',
      'ROLLBACK TO SAVEPOINT imp_classes',
    ]);
    mockTx.createClassTx.mockImplementation(async () => JSON.stringify({ success: true, class: { id: 'class-x' } }));
  });
});

describe('the property library', () => {
  test('a soft-deleted property keeps its name but is not reused', async () => {
    mockTx.getProjectIdBySlugTx.mockImplementation(async () => 'proj-1');
    mockTx.listProjectLibraryPropertiesTx.mockImplementation(async () => [
      { id: 'deleted-1', name: 'email', description: null, data: null, deleted: true },
      { id: 'live-1', name: 'street', description: null, data: { type: 'string' }, deleted: false },
    ]);
    await run();
    const created = (mockTx.createPropertiesBatchTx.mock.calls[0] as any[])[1].map((r: any) => r.name);
    // `email` is taken by the deleted row; `street` is reused, so it is not created again.
    expect(created).toEqual(['address', 'email_1']);
    const [, , propertyRows] = mockTx.createClassesWithPropertiesBulkTx.mock.calls[0] as any[];
    expect(propertyRows.find((r: any) => r.name === 'street').propertyId).toBe('live-1');
    expect(propertyRows.find((r: any) => r.name === 'email').propertyId).not.toBe('deleted-1');
  });

  test('the manifest lists the properties the import added', async () => {
    await run();
    const created = (mockTx.createPropertiesBatchTx.mock.calls[0] as any[])[1].map((r: any) => r.id);
    const [, versionId, manifest] = mockStaging.writeStagedManifestTx.mock.calls[0] as any[];
    expect(versionId).toBe('ver-1');
    expect(manifest).toMatchObject({ projectCreated: true, sourcesCreated: [], sourcesTouched: [] });
    expect(manifest.propertyIds).toEqual(created);
  });
});

describe('verification', () => {
  test('compares counts in the database and reads no rows back', async () => {
    const { status } = await run();
    expect(mockTx.verifyImportCountsTx).toHaveBeenCalledWith(mockClient, 'ver-1', [
      { name: 'Order', properties: 3, discriminator: true },
      { name: 'Customer', properties: 1, discriminator: false },
    ]);
    expect(mockTx.getClassesWithPropertiesAndTagsTx).not.toHaveBeenCalled();
    expect(status.summary?.verification).toEqual({
      passed: true,
      classesVerified: 2,
      propertiesVerified: 4,
      mismatches: [],
    });
    expect(codes(status)).toContain('VERIFY_PASS');
  });

  test('reads the rows back to explain a difference', async () => {
    mockTx.verifyImportCountsTx.mockImplementation(async () => ({ mismatched: ['Customer'], extra: [] }));
    const { status } = await run();
    expect(mockTx.getClassesWithPropertiesAndTagsTx).toHaveBeenCalledTimes(1);
    expect(status.summary?.verification?.passed).toBe(false);
    expect(status.summary?.verification?.mismatches.map((m) => m.type)).toContain('missing_class');
    // A difference is a warning: the import can still be accepted.
    expect(status.state).toBe('pending-approval');
  });

  test('falls back to reading the rows when the comparison cannot run', async () => {
    mockTx.verifyImportCountsTx.mockImplementation(async () => {
      throw new Error('statement timeout');
    });
    await run();
    expect(mockTx.getClassesWithPropertiesAndTagsTx).toHaveBeenCalledTimes(1);
  });

  test('a class the import did not write is reported', async () => {
    mockTx.verifyImportCountsTx.mockImplementation(async () => ({ mismatched: [], extra: ['Legacy'] }));
    const { status } = await run();
    const extra = status.events.find((e) => e.code === 'VERIFY_EXTRA_CLASS');
    expect(extra?.message).toBe('Database contains class "Legacy" that was not in import');
    expect(status.summary?.verification?.passed).toBe(true);
  });
});

describe('staging and decisions', () => {
  test('the project and version are created staged, and the client is released before review', async () => {
    const { status } = await run();
    expect((mockTx.createProjectTx.mock.calls[0] as any[])[7]).toEqual({ pending: true });
    expect((mockTx.createVersionTx.mock.calls[0] as any[])[6]).toMatchObject({ pending: true });
    expect(mockTx.commitTransaction).toHaveBeenCalledTimes(1);
    expect(mockTx.releaseClient).toHaveBeenCalledTimes(1);
    expect(status.transactionPending).toBe(true);
    expect(codes(status)).toEqual(expect.arrayContaining(['IMPORT_STAGED', 'PENDING_APPROVAL']));
  });

  test('Accept flips the staged import in one short transaction', async () => {
    const { jobId } = await run();
    jest.clearAllMocks();
    expect(await commitImport(jobId)).toEqual({ success: true });
    expect(mockStaging.acceptStagedImportTx).toHaveBeenCalledWith(mockClient, 'ver-1', 'user-1');
    expect(mockTx.beginTransaction).toHaveBeenCalledTimes(1);
    expect(mockTx.commitTransaction).toHaveBeenCalledTimes(1);
    expect(mockTx.releaseClient).toHaveBeenCalledTimes(1);
    const status = await getImportStatus(jobId);
    expect(status.state).toBe('completed');
    expect(status.transactionPending).toBe(false);
  });

  test('Accept that finds the plan full rolls back, discards the staged import and says why', async () => {
    const { jobId } = await run();
    mockStaging.acceptStagedImportTx.mockImplementation(async () => ({
      ok: false,
      error: 'Your free plan allows up to 3 version(s). Upgrade or remove a version to add another.',
    }));
    jest.clearAllMocks();
    const result = await commitImport(jobId);
    expect(result).toEqual({
      success: false,
      error: 'Your free plan allows up to 3 version(s). Upgrade or remove a version to add another.',
    });
    expect(mockTx.rollbackTransaction).toHaveBeenCalledTimes(1);
    expect(mockTx.commitTransaction).not.toHaveBeenCalled();
    expect(mockTx.releaseClient).toHaveBeenCalledTimes(1);
    expect(mockStaging.discardStagedImport).toHaveBeenCalledWith('ver-1');
    expect((await getImportStatus(jobId)).state).toBe('failed');
  });

  test('the spec info reaches an existing project only on Accept', async () => {
    mockTx.getProjectIdBySlugTx.mockImplementation(async () => 'proj-1');
    const { jobId, status } = await run({ ...INPUT, sourceKind: 'openapi', document: { openapi: '3.1.0', info: {} } });
    expect(status.state).toBe('pending-approval');
    expect(mockTx.createProjectTx).not.toHaveBeenCalled();
    expect(mockTx.mergeProjectImportOpenApiFieldsTx).not.toHaveBeenCalled();
    await commitImport(jobId);
    expect(mockTx.mergeProjectImportOpenApiFieldsTx).toHaveBeenCalledTimes(1);
    expect((mockTx.mergeProjectImportOpenApiFieldsTx.mock.calls[0] as any[])[1]).toBe('proj-1');
  });

  test('Reject discards the staged import', async () => {
    const { jobId } = await run();
    expect(await rollbackImport(jobId)).toEqual({ success: true });
    expect(mockStaging.discardStagedImport).toHaveBeenCalledWith('ver-1');
    const status = await getImportStatus(jobId);
    expect(status.state).toBe('rolled-back');
    expect(status.transactionPending).toBe(false);
    // Deciding twice does nothing more.
    await rollbackImport(jobId);
    expect(await commitImport(jobId)).toMatchObject({ success: false });
    expect(mockStaging.discardStagedImport).toHaveBeenCalledTimes(1);
  });

  test('a Reject that cannot reach the database leaves the import pending, to retry or be swept', async () => {
    const { jobId } = await run();
    mockStaging.discardStagedImport.mockImplementation(async () => {
      throw new Error('connection refused');
    });
    expect(await rollbackImport(jobId)).toEqual({ success: false, error: 'connection refused' });
    expect((await getImportStatus(jobId)).state).toBe('pending-approval');
  });

  test('canceling an import awaiting approval discards it', async () => {
    const { jobId } = await run();
    expect(await cancelImport(jobId)).toEqual({ success: true });
    expect(mockStaging.discardStagedImport).toHaveBeenCalledWith('ver-1');
  });

  test('canceling a running import rolls its transaction back and stages nothing', async () => {
    let release: () => void = () => undefined;
    mockTx.createClassesWithPropertiesBulkTx.mockImplementation(
      () => new Promise<undefined>((resolve) => (release = () => resolve(undefined))),
    );
    const { jobId } = await startImport(INPUT as never);
    while (mockTx.createClassesWithPropertiesBulkTx.mock.calls.length === 0) {
      await new Promise((resolve) => setTimeout(resolve, 2));
    }
    expect(await cancelImport(jobId)).toEqual({ success: true });
    release();
    let status = await getImportStatus(jobId);
    while (status.state === 'running') {
      await new Promise((resolve) => setTimeout(resolve, 2));
      status = await getImportStatus(jobId);
    }
    expect(status.state).toBe('canceled');
    expect(mockTx.rollbackTransaction).toHaveBeenCalledTimes(1);
    // Nothing was committed, so there is no staged import to discard.
    expect(mockTx.commitTransaction).not.toHaveBeenCalled();
    expect(mockStaging.discardStagedImport).not.toHaveBeenCalled();
    expect(mockTx.releaseClient).toHaveBeenCalledTimes(1);
  });
});

describe('canceling late', () => {
  test('an import canceled after it was staged, before review, is discarded', async () => {
    jest.resetModules();
    let release: () => void = () => undefined;
    jest.doMock('../lib/db/import-openapi-paths-security', () => ({
      importOpenAPIPathsAndSecurity: () =>
        new Promise<{ success: boolean }>((resolve) => (release = () => resolve({ success: true }))),
    }));
    const helper = await import('../lib/db/import-helper');
    const document = { openapi: '3.1.0', info: {}, paths: { '/a': { get: { responses: { '200': { description: 'OK' } } } } } };
    const { jobId } = await helper.startImport({ ...INPUT, sourceKind: 'openapi', document } as never);
    while (!(await helper.getImportStatus(jobId)).events.some((e) => e.code === 'IMPORTING_PATHS')) {
      await new Promise((resolve) => setTimeout(resolve, 2));
    }
    expect(await helper.cancelImport(jobId)).toEqual({ success: true });
    release();
    let status = await helper.getImportStatus(jobId);
    while (status.state === 'running') {
      await new Promise((resolve) => setTimeout(resolve, 2));
      status = await helper.getImportStatus(jobId);
    }
    expect(status.state).toBe('canceled');
    expect(status.transactionPending).toBe(false);
    expect(mockStaging.discardStagedImport).toHaveBeenCalledWith('ver-1');
    jest.dontMock('../lib/db/import-openapi-paths-security');
  });
});
