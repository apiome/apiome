/**
 * Resolution strategy "Create version" in the importer (#590).
 *
 * With `options.onVersionConflict: 'create-version'`, an import into an existing project at a version
 * label the project already has creates the next free sub-version (`1.0.0b`) instead of failing. The
 * label is resolved *before* the INSERT — a duplicate inside the import transaction would abort it —
 * and the job log and summary say which label was used. Without the option, or for a new project, the
 * requested label is passed through untouched.
 */

import { afterEach, beforeEach, describe, expect, jest, test } from '@jest/globals';

const mockCreateVersionTx = jest.fn<(...args: unknown[]) => Promise<string>>();
const mockGetProjectIdBySlugTx = jest.fn<(...args: unknown[]) => Promise<string | null>>();
const mockListVersionLabelsForProjectTx = jest.fn<(...args: unknown[]) => Promise<string[]>>();
const mockClient = { query: jest.fn(), release: jest.fn() };
const ok = (body: Record<string, unknown>) => Promise.resolve(JSON.stringify({ success: true, ...body }));

jest.mock('../lib/db/import-transaction', () => ({
  getTransactionClient: async () => mockClient,
  beginTransaction: async () => undefined,
  commitTransaction: async () => undefined,
  rollbackTransaction: async () => undefined,
  releaseClient: async () => undefined,
  createProjectTx: () => ok({ project: { id: 'proj-new' } }),
  createVersionTx: (...args: unknown[]) => mockCreateVersionTx(...args),
  createPropertiesBatchTx: (_c: unknown, rows: unknown[]) => ok({ inserted: rows.length, failed: [] }),
  createClassTx: (_c: unknown, _v: string, name: string) => ok({ class: { id: `class-${name}` } }),
  addPropertiesToClassBatchTx: (_c: unknown, rows: unknown[]) => ok({ inserted: rows.length, failed: [] }),
  getClassesWithPropertiesAndTagsTx: async () => JSON.stringify([{ name: 'User', schema: {}, properties: [] }]),
  getLatestVersionUuidForProjectTx: async () => null,
  getProjectIdBySlugTx: (...args: unknown[]) => mockGetProjectIdBySlugTx(...args),
  getVersionUuidForCatalogVersionLineTx: async () => null,
  listProjectLibraryPropertiesTx: async () => [],
  listVersionLabelsForProjectTx: (...args: unknown[]) => mockListVersionLabelsForProjectTx(...args),
  mergeProjectImportOpenApiFieldsTx: () => ok({}),
}));

jest.mock('../lib/importers', () => ({
  getImporter: jest.fn(() => ({
    kind: 'openapi',
    normalize: () => ({
      classes: [
        {
          name: 'User',
          description: null,
          schema: { type: 'object' },
          properties: [{ name: 'id', data: { type: 'string' }, description: null }],
        },
      ],
      warnings: [],
    }),
  })),
  ImportSourceKind: { openapi: 'openapi', arazzo: 'arazzo', unknown: 'unknown' },
}));

/** The parts of a job status these tests read. */
interface JobStatus {
  state: string;
  summary: { versionLabelAdjusted?: { requested: string; used: string } };
  events: Array<{ code?: string; message?: string }>;
}

/** Poll until the job leaves queued/running (an incremental import completes on its own). */
async function waitForJobEnd(getImportStatus: (id: string) => Promise<unknown>, jobId: string): Promise<JobStatus> {
  for (let i = 0; i < 200; i += 1) {
    const status = (await getImportStatus(jobId)) as JobStatus;
    if (status.state !== 'queued' && status.state !== 'running') return status;
    await new Promise((r) => setTimeout(r, 25));
  }
  throw new Error('job did not finish');
}

/** The import input, at `version` into the `shop` slug. */
function input(options: Record<string, unknown> = {}, version = '1.0.0') {
  return {
    tenantId: 'tenant-1',
    userId: 'user-1',
    sourceKind: 'openapi' as const,
    document: { openapi: '3.1.0', info: { title: 'Shop', version } },
    project: { name: 'Shop', slug: 'shop', description: null },
    version: { versionId: version, description: null },
    options: { selectedSchemas: ['User'], dryRun: false, incrementalMode: true, ...options },
  };
}

/** The version label the importer asked `createVersionTx` to insert. */
const insertedLabel = () => mockCreateVersionTx.mock.calls[0][3];

describe('importer: create a sub-version on a version conflict (#590)', () => {
  beforeEach(() => {
    mockCreateVersionTx.mockReset();
    mockCreateVersionTx.mockImplementation(() => ok({ version: { id: 'ver-1' } }));
    mockGetProjectIdBySlugTx.mockReset();
    mockGetProjectIdBySlugTx.mockResolvedValue('proj-shop');
    mockListVersionLabelsForProjectTx.mockReset();
    mockListVersionLabelsForProjectTx.mockResolvedValue(['0.9.0', '1.0.0', '1.0.0b']);
  });

  afterEach(() => {
    jest.resetModules();
  });

  test('a taken label becomes the next free sub-version, logged and in the summary', async () => {
    const { startImport, getImportStatus } = await import('../lib/db/import-helper');
    const { jobId } = await startImport(input({ onVersionConflict: 'create-version' }));
    const status = await waitForJobEnd(getImportStatus, jobId);

    expect(status.state).toBe('completed');
    expect(mockListVersionLabelsForProjectTx).toHaveBeenCalledWith(mockClient, 'proj-shop');
    expect(insertedLabel()).toBe('1.0.0c');
    expect(status.summary.versionLabelAdjusted).toEqual({ requested: '1.0.0', used: '1.0.0c' });
    const event = status.events.find((e) => e.code === 'VERSION_LABEL_ADJUSTED');
    expect(event?.message).toBe('Version "1.0.0" already exists in this project; importing as sub-version "1.0.0c".');
  });

  test('a free label is used as asked, with nothing logged', async () => {
    const { startImport, getImportStatus } = await import('../lib/db/import-helper');
    const { jobId } = await startImport(input({ onVersionConflict: 'create-version' }, '2.0.0'));
    const status = await waitForJobEnd(getImportStatus, jobId);
    expect(insertedLabel()).toBe('2.0.0');
    expect(status.summary.versionLabelAdjusted).toBeUndefined();
  });

  test('without the option the requested label goes to the insert untouched', async () => {
    const { startImport, getImportStatus } = await import('../lib/db/import-helper');
    const { jobId } = await startImport(input());
    await waitForJobEnd(getImportStatus, jobId);
    expect(mockListVersionLabelsForProjectTx).not.toHaveBeenCalled();
    expect(insertedLabel()).toBe('1.0.0');
  });

  test('a new project has nothing to conflict with', async () => {
    mockGetProjectIdBySlugTx.mockResolvedValue(null);
    const { startImport, getImportStatus } = await import('../lib/db/import-helper');
    const { jobId } = await startImport(input({ onVersionConflict: 'create-version' }));
    await waitForJobEnd(getImportStatus, jobId);
    expect(mockListVersionLabelsForProjectTx).not.toHaveBeenCalled();
    expect(insertedLabel()).toBe('1.0.0');
  });

  test('the single-transaction import resolves the label before inserting too', async () => {
    const { startImport } = await import('../lib/db/import-helper');
    await startImport(input({ onVersionConflict: 'create-version', incrementalMode: false }));
    for (let i = 0; i < 200 && mockCreateVersionTx.mock.calls.length === 0; i += 1) {
      await new Promise((r) => setTimeout(r, 25));
    }
    expect(insertedLabel()).toBe('1.0.0c');
  });
});
