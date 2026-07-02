/**
 * listTenantRepositoryRefreshSpecs DAO tests (RAR-5.1, #3532).
 *
 * Verifies the SQL contract that backs the repository Specs tab:
 *  - tenant + repository scoping is parameterized (no cross-tenant leak);
 *  - the limit is clamped to 1–200;
 *  - the query joins the recency anchors, operational refresh-job flags, and the
 *    per-repo cadence the client needs to derive refresh status;
 *  - rows are returned verbatim from the pool.
 */

import { describe, test, expect, jest, beforeEach } from '@jest/globals';

// Mock the database connection pool (repository-import-metrics requires './db').
jest.mock('../lib/db/db', () => ({
  query: jest.fn(),
}));

import * as dbModule from '../lib/db/db';
import { listTenantRepositoryRefreshSpecs } from '../lib/db/repository-import-metrics';

const BASE = { tenantId: 'tenant-1', repositoryId: 'repo-1' };

describe('listTenantRepositoryRefreshSpecs (RAR-5.1, #3532)', () => {
  const mockQuery = dbModule.query as unknown as jest.Mock;

  beforeEach(() => {
    mockQuery.mockClear();
    mockQuery.mockResolvedValue({ rowCount: 0, rows: [] });
  });

  test('scopes by tenant and repository and defaults the limit to 100', async () => {
    await listTenantRepositoryRefreshSpecs(BASE);
    expect(mockQuery).toHaveBeenCalledTimes(1);
    const [sql, params] = mockQuery.mock.calls[0] as [string, unknown[]];
    expect(sql).toContain('FROM apiome.repository_import_spec s');
    expect(sql).toContain('s.tenant_id = $1::uuid');
    expect(sql).toContain('s.repository_id = $2::uuid');
    expect(params).toEqual(['tenant-1', 'repo-1', 100]);
  });

  test('joins recency, operational, and cadence signals', async () => {
    await listTenantRepositoryRefreshSpecs(BASE);
    const [sql] = mockQuery.mock.calls[0] as [string, unknown[]];
    // Recency axis.
    expect(sql).toContain('apiome.tenant_repository_files');
    expect(sql).toContain('last_imported_committed_at');
    expect(sql).toContain('remote_committed_at');
    // Operational axis (RAR-3.2 job queue).
    expect(sql).toContain('apiome.tenant_repository_refresh_jobs');
    expect(sql).toContain('is_refreshing');
    expect(sql).toContain('last_refresh_failed');
    // Cadence (RAR-3.1) for next-due.
    expect(sql).toContain('refresh_interval_seconds');
    expect(sql).toContain('auto_refresh_enabled');
  });

  test('clamps the limit to the 1–200 window', async () => {
    await listTenantRepositoryRefreshSpecs({ ...BASE, limit: 9999 });
    expect((mockQuery.mock.calls[0] as [string, unknown[]])[1]).toEqual(['tenant-1', 'repo-1', 200]);

    mockQuery.mockClear();
    await listTenantRepositoryRefreshSpecs({ ...BASE, limit: 0 });
    expect((mockQuery.mock.calls[0] as [string, unknown[]])[1]).toEqual(['tenant-1', 'repo-1', 1]);
  });

  test('returns the pool rows verbatim', async () => {
    const rows = [{ id: 'spec-1', path: 'specs/petstore.yaml', branch: 'main' }];
    mockQuery.mockResolvedValue({ rowCount: rows.length, rows });
    const result = await listTenantRepositoryRefreshSpecs(BASE);
    expect(result).toBe(rows);
  });
});
