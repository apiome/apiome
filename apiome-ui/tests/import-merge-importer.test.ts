/**
 * Merge strategies in the importer: additive (#591) and override (#592).
 *
 * With `options.mergeStrategy: 'additive'`, an import into an existing project keeps everything the
 * latest version has and adds what the spec newly defines: a same-named class keeps its properties
 * and gains the new ones, classes and paths only the latest version has are copied forward, a path
 * both sides have gains only new operations, and the latest version's security schemes are not
 * replaced. With `override`, the same is carried and added, but the spec's definition wins where both
 * define a property, an operation or a security scheme. Without the option, for a first import, or
 * for a registered-repository import, nothing is merged.
 */

import { afterEach, beforeEach, describe, expect, jest, test } from '@jest/globals';

const PARENT = 'ver-parent';
const NEW = 'ver-new';

const mockCreateVersionTx = jest.fn<(...args: unknown[]) => Promise<string>>();
const mockCreateClassTx = jest.fn<(...args: unknown[]) => Promise<string>>();
const mockLatestVersion = jest.fn<(...args: unknown[]) => Promise<string | null>>();
const mockCopyClassesTx = jest.fn<(...args: unknown[]) => Promise<number>>();
const mockCopySecuritySchemesTx = jest.fn<(...args: unknown[]) => Promise<void>>();
const mockLoadCarriedPaths = jest.fn<(...args: unknown[]) => Promise<unknown[]>>();
const mockImportPaths = jest.fn<(...args: unknown[]) => Promise<{ success: boolean }>>();
const mockClient = {
  query: jest.fn(async (sql: unknown) => {
    const text = String(sql);
    if (text.includes('FROM apiome.version_path')) return { rows: [{ pathname: '/pets' }, { pathname: '/owners' }] };
    if (text.includes('FROM apiome.version_security_scheme')) return { rows: [{ scheme_name: 'apiKey' }] };
    return { rows: [] };
  }),
  release: jest.fn(),
};
const ok = (body: Record<string, unknown>) => Promise.resolve(JSON.stringify({ success: true, ...body }));

/** The latest version's classes as stored: Pet (id, name) and Owner (id). */
const PARENT_CLASSES = [
  {
    id: 'c-pet',
    name: 'Pet',
    description: 'Stored pet',
    schema: { type: 'object' },
    properties: [
      { id: 'p1', name: 'id', data: { type: 'integer' }, parent_id: null },
      { id: 'p2', name: 'name', data: { type: 'string', maxLength: 50 }, parent_id: null },
    ],
  },
  { id: 'c-owner', name: 'Owner', schema: { type: 'object' }, properties: [{ id: 'p3', name: 'id', data: { type: 'integer' } }] },
];

jest.mock('../lib/db/import-transaction', () => ({
  getTransactionClient: async () => mockClient,
  beginTransaction: async () => undefined,
  commitTransaction: async () => undefined,
  rollbackTransaction: async () => undefined,
  releaseClient: async () => undefined,
  createProjectTx: () => ok({ project: { id: 'proj-new' } }),
  createVersionTx: (...args: unknown[]) => mockCreateVersionTx(...args),
  createPropertiesBatchTx: (_c: unknown, rows: unknown[]) => ok({ inserted: rows.length, failed: [] }),
  createClassTx: (...args: unknown[]) => mockCreateClassTx(...args),
  addPropertiesToClassBatchTx: (_c: unknown, rows: unknown[]) => ok({ inserted: rows.length, failed: [] }),
  getClassesWithPropertiesAndTagsTx: async (_c: unknown, versionId: string) =>
    JSON.stringify(versionId === PARENT ? PARENT_CLASSES : []),
  getLatestVersionUuidForProjectTx: (...args: unknown[]) => mockLatestVersion(...args),
  getProjectIdBySlugTx: async () => 'proj-shop',
  getVersionUuidForCatalogVersionLineTx: async () => null,
  listProjectLibraryPropertiesTx: async () => [],
  listVersionLabelsForProjectTx: async () => [],
  mergeProjectImportOpenApiFieldsTx: () => ok({}),
}));

jest.mock('../lib/db/repository-merge', () => ({
  ...(jest.requireActual('../lib/db/repository-merge') as object),
  copyClassesTx: (...args: unknown[]) => mockCopyClassesTx(...args),
  copySecuritySchemesTx: (...args: unknown[]) => mockCopySecuritySchemesTx(...args),
  loadCarriedPaths: (...args: unknown[]) => mockLoadCarriedPaths(...args),
  loadIncomingSource: async () => null,
}));

jest.mock('../lib/db/import-openapi-paths-security', () => ({
  importOpenAPIPathsAndSecurity: (...args: unknown[]) => mockImportPaths(...args),
}));

jest.mock('../lib/db/repository-import-metrics', () => ({
  recordTenantRepositoryImport: async () => undefined,
  upsertRepositoryImportSpec: async () => undefined,
}));

jest.mock('../lib/importers', () => ({
  getImporter: jest.fn(() => ({
    kind: 'openapi',
    normalize: () => ({
      classes: [
        {
          name: 'Pet',
          description: 'Spec pet',
          schema: { type: 'object' },
          properties: [
            { name: 'name', data: { type: 'string', maxLength: 10 }, description: null },
            { name: 'tag', data: { type: 'string' }, description: null },
          ],
        },
        { name: 'Tag', description: null, schema: { type: 'object' }, properties: [{ name: 'label', data: { type: 'string' } }] },
      ],
      warnings: [],
    }),
  })),
  ImportSourceKind: { openapi: 'openapi', arazzo: 'arazzo', unknown: 'unknown' },
}));

/** The spec: GET+POST /pets and GET /tags, with an `apiKey` and a `bearer` security scheme. */
const DOCUMENT = {
  openapi: '3.1.0',
  info: { title: 'Shop', version: '2.0.0' },
  paths: {
    '/pets': { get: { responses: { '200': { description: 'ok' } } }, post: { responses: { '201': { description: 'ok' } } } },
    '/tags': { get: { responses: { '200': { description: 'ok' } } } },
  },
  components: {
    securitySchemes: {
      apiKey: { type: 'apiKey', in: 'query', name: 'key' },
      bearer: { type: 'http', scheme: 'bearer' },
    },
  },
};

/** The parts of a job status these tests read. */
interface JobStatus {
  state: string;
  summary: { importMerge?: Record<string, unknown>; classesCreated: number };
  events: Array<{ code?: string; message?: string }>;
}

/** Poll until the job leaves queued/running. */
async function waitForJobEnd(getImportStatus: (id: string) => Promise<unknown>, jobId: string): Promise<JobStatus> {
  for (let i = 0; i < 200; i += 1) {
    const status = (await getImportStatus(jobId)) as JobStatus;
    if (status.state !== 'queued' && status.state !== 'running') return status;
    await new Promise((r) => setTimeout(r, 25));
  }
  throw new Error('job did not finish');
}

/** The import input into the `shop` slug. */
function input(options: Record<string, unknown> = {}, extra: Record<string, unknown> = {}) {
  return {
    tenantId: 'tenant-1',
    userId: 'user-1',
    sourceKind: 'openapi' as const,
    document: DOCUMENT,
    project: { name: 'Shop', slug: 'shop', description: null },
    version: { versionId: '2.0.0', description: null },
    options: { selectedSchemas: ['Pet', 'Tag'], dryRun: false, incrementalMode: true, ...options },
    ...extra,
  };
}

/** Names of the classes the importer created, in order. */
function writtenClassNames(): string[] {
  return mockCreateClassTx.mock.calls.map((c) => c[2] as string);
}

describe('importer: merge strategies (#591, #592)', () => {
  beforeEach(() => {
    mockCreateVersionTx.mockReset();
    mockCreateVersionTx.mockImplementation(() => ok({ version: { id: NEW } }));
    mockCreateClassTx.mockReset();
    mockCreateClassTx.mockImplementation((_c, _v, name) => ok({ class: { id: `class-${String(name)}` } }));
    mockLatestVersion.mockReset();
    mockLatestVersion.mockResolvedValue(PARENT);
    mockCopyClassesTx.mockReset();
    mockCopyClassesTx.mockImplementation(async (...args) => (args[3] as string[]).length);
    mockCopySecuritySchemesTx.mockReset();
    mockCopySecuritySchemesTx.mockResolvedValue(undefined);
    mockLoadCarriedPaths.mockReset();
    mockLoadCarriedPaths.mockResolvedValue([
      { path: '/pets', operations: [{ method: 'GET', summary: 'stored', parameters: [], responses: {} }] },
      { path: '/owners', operations: [{ method: 'GET', parameters: [], responses: {} }] },
    ]);
    mockImportPaths.mockReset();
    mockImportPaths.mockResolvedValue({ success: true });
  });

  afterEach(() => {
    jest.resetModules();
  });

  test('merges classes, carries the rest, and writes the merged paths', async () => {
    const { startImport, getImportStatus } = await import('../lib/db/import-helper');
    const { jobId } = await startImport(input({ mergeStrategy: 'additive' }));
    const status = await waitForJobEnd(getImportStatus, jobId);

    expect(status.state).toBe('completed');
    expect(writtenClassNames()).toEqual(['Pet', 'Tag']);
    // Pet is written with its stored description (existing metadata kept).
    expect(mockCreateClassTx.mock.calls[0][3]).toBe('Stored pet');
    expect(mockCopyClassesTx).toHaveBeenCalledWith(mockClient, PARENT, NEW, ['Owner']);
    expect(mockCopySecuritySchemesTx).toHaveBeenCalledWith(mockClient, PARENT, NEW);
    expect(mockLoadCarriedPaths).toHaveBeenCalledWith(PARENT, ['/pets', '/owners']);

    const [versionId, paths, schemes] = mockImportPaths.mock.calls[0] as [
      string,
      Array<{ path: string; operations: Array<{ method: string; summary?: string }> }>,
      Array<{ scheme_name: string }>,
    ];
    expect(versionId).toBe(NEW);
    expect(paths.map((p) => p.path)).toEqual(['/pets', '/owners', '/tags']);
    expect(paths[0].operations.map((o) => [o.method, o.summary])).toEqual([
      ['GET', 'stored'],
      ['POST', undefined],
    ]);
    // The stored `apiKey` scheme is kept: only the spec's new `bearer` scheme is written.
    expect(schemes.map((s) => s.scheme_name)).toEqual(['bearer']);

    expect(status.summary.importMerge).toEqual({
      strategy: 'additive',
      schemasMerged: 1,
      propertiesAdded: 1,
      propertiesUpdated: 0,
      schemasCarried: 1,
      pathsCarried: 1,
      operationsAdded: 1,
      operationsUpdated: 0,
    });
    expect(status.events.some((e) => e.code === 'IMPORT_MERGE')).toBe(true);
    // Carried classes are expected in the new version, not reported as extras.
    expect(status.events.some((e) => e.code === 'VERIFY_EXTRA_CLASS')).toBe(false);
  });

  test('the single-transaction import copies the kept classes in its transaction', async () => {
    const { startImport, getImportStatus } = await import('../lib/db/import-helper');
    const { jobId } = await startImport(input({ mergeStrategy: 'additive', incrementalMode: false }));
    const status = await waitForJobEnd(getImportStatus, jobId);
    expect(status.state).toBe('pending-approval');
    expect(mockCopyClassesTx).toHaveBeenCalledWith(mockClient, PARENT, NEW, ['Owner']);
    expect(status.summary.importMerge?.schemasCarried).toBe(1);
  });

  test('a dry run reports the merge without writing', async () => {
    const { startImport, getImportStatus } = await import('../lib/db/import-helper');
    const { jobId } = await startImport(input({ mergeStrategy: 'additive', dryRun: true }));
    const status = await waitForJobEnd(getImportStatus, jobId);
    expect(status.state).toBe('completed');
    expect(status.summary.importMerge?.schemasMerged).toBe(1);
    expect(mockCreateClassTx).not.toHaveBeenCalled();
    expect(mockCopyClassesTx).not.toHaveBeenCalled();
  });

  test('without the option nothing is merged or carried', async () => {
    const { startImport, getImportStatus } = await import('../lib/db/import-helper');
    const { jobId } = await startImport(input());
    const status = await waitForJobEnd(getImportStatus, jobId);
    expect(status.summary.importMerge).toBeUndefined();
    expect(mockCopyClassesTx).not.toHaveBeenCalled();
    expect(mockLoadCarriedPaths).not.toHaveBeenCalled();
    expect(mockCreateClassTx.mock.calls[0][3]).toBe('Spec pet');
    const paths = mockImportPaths.mock.calls[0][1] as Array<{ path: string }>;
    expect(paths.map((p) => p.path)).toEqual(['/pets', '/tags']);
  });

  test('with no latest version the option is ignored with a warning', async () => {
    mockLatestVersion.mockResolvedValue(null);
    const { startImport, getImportStatus } = await import('../lib/db/import-helper');
    const { jobId } = await startImport(input({ mergeStrategy: 'additive' }));
    const status = await waitForJobEnd(getImportStatus, jobId);
    expect(status.summary.importMerge).toBeUndefined();
    expect(status.events.some((e) => e.code === 'IMPORT_MERGE_IGNORED')).toBe(true);
    expect(mockCopyClassesTx).not.toHaveBeenCalled();
  });

  test('a registered-repository import leaves carrying to federation', async () => {
    const { startImport, getImportStatus } = await import('../lib/db/import-helper');
    const { jobId } = await startImport(
      input({ mergeStrategy: 'additive' }, { repositorySource: { repositoryId: 'repo-1', branch: 'main', path: 'api.yaml' } }),
    );
    const status = await waitForJobEnd(getImportStatus, jobId);
    expect(status.summary.importMerge).toBeUndefined();
    expect(status.events.find((e) => e.code === 'IMPORT_MERGE_IGNORED')?.message).toMatch(/repository/);
  });

  test('override: the spec wins where both define something; the rest is kept (#592)', async () => {
    const { startImport, getImportStatus } = await import('../lib/db/import-helper');
    const { jobId } = await startImport(input({ mergeStrategy: 'override' }));
    const status = await waitForJobEnd(getImportStatus, jobId);

    expect(status.state).toBe('completed');
    expect(writtenClassNames()).toEqual(['Pet', 'Tag']);
    // Pet takes the spec's description.
    expect(mockCreateClassTx.mock.calls[0][3]).toBe('Spec pet');
    expect(mockCopyClassesTx).toHaveBeenCalledWith(mockClient, PARENT, NEW, ['Owner']);

    const [, paths, schemes] = mockImportPaths.mock.calls[0] as [
      string,
      Array<{ path: string; operations: Array<{ method: string; summary?: string }> }>,
      Array<{ scheme_name: string }>,
    ];
    expect(paths.map((p) => p.path)).toEqual(['/pets', '/owners', '/tags']);
    // The spec's GET replaces the stored one (no "stored" summary); POST is added.
    expect(paths[0].operations.map((o) => [o.method, o.summary])).toEqual([
      ['GET', undefined],
      ['POST', undefined],
    ]);
    // The spec's same-named `apiKey` scheme is written too, so it replaces the stored one.
    expect(schemes.map((s) => s.scheme_name)).toEqual(['apiKey', 'bearer']);

    expect(status.summary.importMerge).toEqual({
      strategy: 'override',
      schemasMerged: 1,
      propertiesAdded: 1,
      propertiesUpdated: 1,
      schemasCarried: 1,
      pathsCarried: 1,
      operationsAdded: 1,
      operationsUpdated: 1,
    });
    expect(status.events.find((e) => e.code === 'IMPORT_MERGE')?.message).toMatch(/^Override merge:/);
  });

  test('override is ignored with a warning when there is no latest version (#592)', async () => {
    mockLatestVersion.mockResolvedValue(null);
    const { startImport, getImportStatus } = await import('../lib/db/import-helper');
    const { jobId } = await startImport(input({ mergeStrategy: 'override' }));
    const status = await waitForJobEnd(getImportStatus, jobId);
    expect(status.summary.importMerge).toBeUndefined();
    expect(status.events.find((e) => e.code === 'IMPORT_MERGE_IGNORED')?.message).toMatch(/^Override merge needs/);
  });
});
