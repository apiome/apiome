/**
 * Import benchmarking tests.
 *
 * The import accumulates per-phase / per-DB-op timing so a slow import can be
 * attributed (parse vs DB writes, and which DB op). This verifies the breakdown
 * is produced on the job summary and surfaced as a BENCHMARK event.
 */

import { describe, test, expect, beforeEach, afterEach, jest } from '@jest/globals';

const ok = (obj: Record<string, unknown>) => JSON.stringify({ success: true, ...obj });

const mockClient = { query: jest.fn(), release: jest.fn() };

jest.mock('../lib/db/import-transaction', () => ({
  getTransactionClient: jest.fn(() => Promise.resolve(mockClient)),
  beginTransaction: jest.fn(() => Promise.resolve(undefined)),
  commitTransaction: jest.fn(() => Promise.resolve(undefined)),
  rollbackTransaction: jest.fn(() => Promise.resolve(undefined)),
  releaseClient: jest.fn(() => Promise.resolve(undefined)),
  createProjectTx: jest.fn(() => Promise.resolve(ok({ project: { id: 'p1' } }))),
  createVersionTx: jest.fn(() => Promise.resolve(ok({ version: { id: 'v1' } }))),
  createPropertyTx: jest.fn(() => Promise.resolve(ok({ property: { id: 'prop1' } }))),
  createPropertiesBatchTx: jest.fn((_client: unknown, rows: unknown[]) =>
    Promise.resolve(ok({ inserted: Array.isArray(rows) ? rows.length : 0, failed: [] }))),
  createClassTx: jest.fn(() => Promise.resolve(ok({ class: { id: 'c1' } }))),
  addPropertyToClassTx: jest.fn(() => Promise.resolve(ok({ classProperty: { id: 'cp1' } }))),
  addPropertiesToClassBatchTx: jest.fn((_client: unknown, rows: unknown[]) =>
    Promise.resolve(ok({ inserted: Array.isArray(rows) ? rows.length : 0 }))),
  getClassesWithPropertiesAndTagsTx: jest.fn(() => Promise.resolve('[]')),
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
  ],
  warnings: [] as string[],
};

jest.mock('../lib/importers', () => ({
  getImporter: jest.fn(() => ({ kind: 'openapi', normalize: () => mockNormalizeResult })),
  ImportSourceKind: { openapi: 'openapi', arazzo: 'arazzo', unknown: 'unknown' },
}));

async function waitForJobEnd(
  getImportStatus: (jobId: string) => Promise<any>,
  jobId: string,
  maxMs = 3000,
): Promise<any> {
  const start = Date.now();
  while (Date.now() - start < maxMs) {
    const status = await getImportStatus(jobId);
    if (!['queued', 'running', 'committing'].includes(status.state)) return status;
    await new Promise((r) => setTimeout(r, 20));
  }
  throw new Error(`Job ${jobId} did not finish within ${maxMs}ms`);
}

const baseInput = {
  tenantId: 'tenant-1',
  userId: 'user-1',
  sourceKind: 'openapi' as const,
  document: { openapi: '3.1.0', info: { title: 'Test API', version: '1.0.0' } },
  project: { name: 'Bench Project', slug: 'bench-project', description: null },
  version: { versionId: '1.0.0', description: null },
};

describe('Import benchmarking', () => {
  beforeEach(() => {
    jest.spyOn(console, 'error').mockImplementation(() => {});
  });
  afterEach(() => {
    jest.resetModules();
    jest.restoreAllMocks();
  });

  test('dry run produces a benchmark with the parse span and a BENCHMARK event', async () => {
    const { startImport, getImportStatus } = await import('../lib/db/import-helper');
    const { jobId } = await startImport({
      ...baseInput,
      options: { selectedSchemas: ['User'], dryRun: true },
    });

    const status = await waitForJobEnd(getImportStatus, jobId);

    expect(status.state).toBe('completed');
    const bench = status.summary?.benchmark;
    expect(bench).toBeDefined();
    expect(typeof bench.totalMs).toBe('number');
    const names = bench.spans.map((s: any) => s.name);
    expect(names).toContain('parse:normalize');
    // Spans are sorted slowest-first and carry count/avg/pct.
    expect(bench.spans[0]).toEqual(
      expect.objectContaining({ name: expect.any(String), ms: expect.any(Number), count: expect.any(Number) }),
    );
    expect(status.events.some((e: any) => e.code === 'BENCHMARK')).toBe(true);
  });

  test('incremental import records per-DB-op spans so N+1 writes are visible', async () => {
    const { startImport, getImportStatus } = await import('../lib/db/import-helper');
    const { jobId } = await startImport({
      ...baseInput,
      options: { selectedSchemas: ['User'], dryRun: false, incrementalMode: true },
    });

    const status = await waitForJobEnd(getImportStatus, jobId);

    expect(status.state).toBe('completed');
    const names = (status.summary?.benchmark?.spans ?? []).map((s: any) => s.name);
    expect(names).toContain('parse:normalize');
    // Library properties are created in a single batched insert (not one round-trip each).
    expect(names).toContain('db:createPropertiesBatch');
    expect(names).toContain('db:createClass');
    // Properties are written in a single batched insert per class (not one round-trip each).
    expect(names).toContain('db:addPropertiesToClassBatch');
    expect(names).toContain('phase:writeClasses');

    // Both distinct shapes (id, email) are created in one batched insert -> a single round-trip.
    const createProp = status.summary.benchmark.spans.find((s: any) => s.name === 'db:createPropertiesBatch');
    expect(createProp.count).toBe(1);

    // Per-phase timing is emitted live (as PHASE_TIMING events) so it can be followed
    // while the import runs, not only in the final BENCHMARK summary.
    const phaseEvents = status.events.filter((e: any) => e.code === 'PHASE_TIMING');
    expect(phaseEvents.length).toBeGreaterThan(0);
    const phaseNames = phaseEvents.map((e: any) => e.context?.phase);
    expect(phaseNames).toContain('phase:writeClasses');
    expect(phaseEvents[0].context).toEqual(
      expect.objectContaining({ phase: expect.any(String), ms: expect.any(Number) }),
    );
  });
});
