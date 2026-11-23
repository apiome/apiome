/**
 * @jest-environment node
 *
 * Staged imports against a real PostgreSQL (DBP-1.9, #7192): Accept, Reject and an abandoned
 * import each leave the database consistent, including after a process restart, and no pooled
 * client is held while an import awaits approval.
 *
 * Skipped unless `IMPORT_STAGING_TEST_DATABASE_URL` names a migrated database (V411 or later):
 *
 *   createdb apiome_staging
 *   node apiome-db/dist/cli.js migrate --database-url postgresql://localhost:5432/apiome_staging
 *   IMPORT_STAGING_TEST_DATABASE_URL=postgresql://localhost:5432/apiome_staging \
 *     yarn workspace apiome-ui jest tests/import-staging-db.test.ts
 *
 * The suite creates its own tenant and user and removes everything it wrote.
 * `tests/import-staging.test.ts` and `tests/import-pipeline-budget.test.ts` cover the same paths
 * without a database.
 */

import { randomUUID } from 'crypto';
import { afterAll, beforeAll, describe, expect, jest, test } from '@jest/globals';

const DATABASE_URL = process.env.IMPORT_STAGING_TEST_DATABASE_URL;
const describeDb = DATABASE_URL ? describe : describe.skip;

jest.mock('../lib/db/helper', () => ({
  permanentDeleteProject: jest.fn(),
  getTenantById: jest.fn(),
}));

const TENANT = randomUUID();
const USER = randomUUID();
const RUN = randomUUID().slice(0, 8);

/** A small OpenAPI document: two schemas, one path with two operations, one security scheme. */
function specification(extraProperty?: string): Record<string, unknown> {
  return {
    openapi: '3.1.0',
    info: { title: 'Staging', version: '1.0.0', description: 'From the specification' },
    paths: {
      '/pets/{id}': {
        parameters: [{ name: 'id', in: 'path', required: true, schema: { type: 'string' } }],
        get: {
          operationId: 'getPet',
          responses: { '200': { description: 'OK', content: { 'application/json': { schema: { $ref: '#/components/schemas/Pet' } } } } },
        },
        put: {
          operationId: 'putPet',
          requestBody: { content: { 'application/json': { schema: { $ref: '#/components/schemas/Pet' } } } },
          responses: { '204': { description: 'Saved' } },
        },
      },
    },
    components: {
      schemas: {
        Pet: {
          type: 'object',
          properties: {
            petName: { type: 'string', maxLength: 40 },
            owner: { $ref: '#/components/schemas/Owner' },
            ...(extraProperty ? { [extraProperty]: { type: 'integer', minimum: 7 } } : {}),
          },
        },
        Owner: { type: 'object', properties: { ownerEmail: { type: 'string', format: 'email' } } },
      },
      securitySchemes: { key: { type: 'apiKey', in: 'header', name: 'X-Key' } },
    },
  };
}

type Helper = typeof import('../lib/db/import-helper');
type Staging = typeof import('../lib/db/import-staging');
type Pool = {
  query: (sql: string, params?: unknown[]) => Promise<{ rows: Record<string, any>[] }>; // eslint-disable-line @typescript-eslint/no-explicit-any
  end: () => Promise<void>;
  totalCount: number;
  idleCount: number;
  waitingCount: number;
};

/** The modules of one "process": a fresh registry has an empty job table and its own pool. */
function load(): { helper: Helper; staging: Staging; pool: Pool } {
  /* eslint-disable @typescript-eslint/no-require-imports */
  return {
    helper: require('../lib/db/import-helper'),
    staging: require('../lib/db/import-staging'),
    pool: require('../lib/db/db'),
  };
  /* eslint-enable @typescript-eslint/no-require-imports */
}

/** Stage an import and wait until it stops running. */
async function stage(helper: Helper, slug: string, document = specification()) {
  const { jobId } = await helper.startImport({
    tenantId: TENANT,
    userId: USER,
    sourceKind: 'openapi',
    document,
    project: { name: `Staging ${slug}`, slug },
    version: { versionId: String((document.info as { version: string }).version) },
    options: { selectedSchemas: Object.keys((document.components as { schemas: object }).schemas) },
  } as never);
  for (;;) {
    const status = await helper.getImportStatus(jobId);
    if (status.state !== 'queued' && status.state !== 'running') return { jobId, status };
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
}

/** Row counts for a project and one of its versions, whatever their state. */
async function census(pool: Pool, projectId: string, versionId: string) {
  const result = await pool.query(
    `SELECT (SELECT count(*) FROM apiome.projects WHERE id = $1)::int AS projects,
            (SELECT count(*) FROM apiome.projects WHERE id = $1 AND deleted_at IS NULL)::int AS live_projects,
            (SELECT count(*) FROM apiome.versions WHERE id = $2)::int AS versions,
            (SELECT count(*) FROM apiome.versions WHERE id = $2 AND deleted_at IS NULL)::int AS live_versions,
            (SELECT count(*) FROM apiome.versions WHERE id = $2 AND import_pending_at IS NOT NULL)::int AS staged_versions,
            (SELECT count(*) FROM apiome.classes WHERE version_id = $2)::int AS classes,
            (SELECT count(*) FROM apiome.class_properties cp JOIN apiome.classes c ON c.id = cp.class_id
              WHERE c.version_id = $2)::int AS class_properties,
            (SELECT count(*) FROM apiome.properties WHERE project_id = $1)::int AS properties,
            (SELECT count(*) FROM apiome.version_path WHERE version_id = $2)::int AS paths,
            (SELECT count(*) FROM apiome.path_operation o JOIN apiome.version_path vp ON vp.id = o.version_path_id
              WHERE vp.version_id = $2)::int AS operations,
            (SELECT count(*) FROM apiome.version_security_scheme WHERE version_id = $2)::int AS schemes`,
    [projectId, versionId],
  );
  return result.rows[0];
}

const NOTHING = {
  projects: 0, live_projects: 0, versions: 0, live_versions: 0, staged_versions: 0,
  classes: 0, class_properties: 0, properties: 0, paths: 0, operations: 0, schemes: 0,
};
const IMPORTED = { classes: 2, class_properties: 3, properties: 2, paths: 1, operations: 2, schemes: 1 };

describeDb('staged imports against PostgreSQL (DBP-1.9)', () => {
  let current: ReturnType<typeof load>;

  beforeAll(async () => {
    process.env.DATABASE_URL = DATABASE_URL;
    jest.spyOn(console, 'error').mockImplementation(() => undefined);
    jest.resetModules();
    current = load();
    const { pool } = current;
    await pool.query(
      `INSERT INTO apiome.users (id, name, email, password) VALUES ($1, 'Staging test', $2, 'x')`,
      [USER, `staging-${RUN}@example.test`],
    );
    await pool.query(`INSERT INTO apiome.tenants (id, name, slug) VALUES ($1, 'Staging test', $2)`, [
      TENANT,
      `staging-${RUN}`,
    ]);
    await pool.query(`INSERT INTO apiome.tenant_users (tenant_id, user_id) VALUES ($1, $2)`, [TENANT, USER]);
  });

  afterAll(async () => {
    const { pool, staging } = current;
    await staging.sweepAbandonedImports({ ttlMs: 0 });
    const projects = `SELECT id FROM apiome.projects WHERE tenant_id = $1`;
    const versions = `SELECT id FROM apiome.versions WHERE project_id IN (${projects})`;
    await pool.query(`DELETE FROM apiome.version_path WHERE version_id IN (${versions})`, [TENANT]);
    await pool.query(`DELETE FROM apiome.classes WHERE version_id IN (${versions})`, [TENANT]);
    await pool.query(`DELETE FROM apiome.versions WHERE project_id IN (${projects})`, [TENANT]);
    await pool.query(`DELETE FROM apiome.properties WHERE project_id IN (${projects})`, [TENANT]);
    await pool.query(`DELETE FROM apiome.projects WHERE tenant_id = $1`, [TENANT]);
    await pool.query(`DELETE FROM apiome.tenant_users WHERE tenant_id = $1`, [TENANT]);
    await pool.query(`DELETE FROM apiome.tenants WHERE id = $1`, [TENANT]);
    await pool.query(`DELETE FROM apiome.users WHERE id = $1`, [USER]);
    await pool.end();
  });

  test('a staged import is committed, hidden, and holds no pooled client', async () => {
    const { helper, pool } = current;
    const { jobId, status } = await stage(helper, `hidden-${RUN}`);
    expect(status.state).toBe('pending-approval');
    const { projectId, versionId } = status.result as { projectId: string; versionId: string };

    // Committed: another connection sees the rows. Hidden: none of them is live.
    expect(await census(pool, projectId, versionId)).toEqual({
      ...IMPORTED, projects: 1, live_projects: 0, versions: 1, live_versions: 0, staged_versions: 1,
    });
    // Every client the pool has is idle while the reviewer decides.
    expect(pool.totalCount).toBeGreaterThan(0);
    expect(pool.idleCount).toBe(pool.totalCount);
    expect(pool.waitingCount).toBe(0);

    await helper.rollbackImport(jobId);
  });

  test('Accept makes the import visible and clears the staging columns', async () => {
    const { helper, pool } = current;
    const { jobId, status } = await stage(helper, `accept-${RUN}`);
    const { projectId, versionId } = status.result as { projectId: string; versionId: string };

    expect(await helper.commitImport(jobId)).toEqual({ success: true });
    expect((await helper.getImportStatus(jobId)).state).toBe('completed');
    expect(await census(pool, projectId, versionId)).toEqual({
      ...IMPORTED, projects: 1, live_projects: 1, versions: 1, live_versions: 1, staged_versions: 0,
    });
    const version = await pool.query('SELECT import_pending FROM apiome.versions WHERE id = $1', [versionId]);
    expect(version.rows[0].import_pending).toBeNull();
    expect(pool.idleCount).toBe(pool.totalCount);
  });

  test('Reject removes a new project and everything in it', async () => {
    const { helper, pool } = current;
    const { jobId, status } = await stage(helper, `reject-${RUN}`);
    const { projectId, versionId } = status.result as { projectId: string; versionId: string };

    expect(await helper.rollbackImport(jobId)).toEqual({ success: true });
    expect((await helper.getImportStatus(jobId)).state).toBe('rolled-back');
    expect(await census(pool, projectId, versionId)).toEqual(NOTHING);
    // The slug is free again.
    const again = await stage(helper, `reject-${RUN}`);
    expect(again.status.state).toBe('pending-approval');
    await helper.rollbackImport(again.jobId);
  });

  test('Reject of a new version leaves the existing project as it was', async () => {
    const { helper, pool } = current;
    const slug = `existing-${RUN}`;
    const first = await stage(helper, slug);
    await helper.commitImport(first.jobId);
    const { projectId, versionId: firstVersion } = first.status.result as { projectId: string; versionId: string };
    await pool.query(`UPDATE apiome.projects SET description = NULL, metadata = '{}' WHERE id = $1`, [projectId]);
    const before = await census(pool, projectId, firstVersion);

    const next = specification('weight');
    (next.info as { version: string }).version = '2.0.0';
    const second = await stage(helper, slug, next);
    expect(second.status.state).toBe('pending-approval');
    const secondVersion = (second.status.result as { versionId: string }).versionId;
    // Staged: the new property is in the library, but the project itself is untouched.
    expect((await census(pool, projectId, secondVersion)).properties).toBe(before.properties + 1);
    const untouched = await pool.query('SELECT description, deleted_at FROM apiome.projects WHERE id = $1', [projectId]);
    expect(untouched.rows[0]).toEqual({ description: null, deleted_at: null });

    await helper.rollbackImport(second.jobId);
    expect(await census(pool, projectId, firstVersion)).toEqual(before);
    expect((await census(pool, projectId, secondVersion)).versions).toBe(0);
  });

  test('Accept of a new version merges the specification info into the existing project', async () => {
    const { helper, pool } = current;
    const slug = `merge-${RUN}`;
    const first = await stage(helper, slug);
    await helper.commitImport(first.jobId);
    const { projectId } = first.status.result as { projectId: string };
    await pool.query(`UPDATE apiome.projects SET description = NULL WHERE id = $1`, [projectId]);

    const next = specification();
    (next.info as { version: string }).version = '2.0.0';
    const second = await stage(helper, slug, next);
    const pending = await pool.query('SELECT description FROM apiome.projects WHERE id = $1', [projectId]);
    expect(pending.rows[0].description).toBeNull();

    expect(await helper.commitImport(second.jobId)).toEqual({ success: true });
    const merged = await pool.query('SELECT description FROM apiome.projects WHERE id = $1', [projectId]);
    expect(merged.rows[0].description).toBe('From the specification');
    const versions = await pool.query(
      'SELECT count(*)::int AS live FROM apiome.versions WHERE project_id = $1 AND deleted_at IS NULL',
      [projectId],
    );
    expect(versions.rows[0].live).toBe(2);
  });

  test('an import abandoned by a restart is swept once it is old enough', async () => {
    const { helper, pool } = current;
    const { jobId, status } = await stage(helper, `restart-${RUN}`);
    const { projectId, versionId } = status.result as { projectId: string; versionId: string };

    // The process dies: its pool closes, and the job table is gone with it.
    await pool.end();
    jest.resetModules();
    current = load();
    const restarted = current;
    expect((await restarted.helper.getImportStatus(jobId)).state).toBe('failed');
    expect(await restarted.helper.commitImport(jobId)).toEqual({ success: false, error: 'Job not found' });

    // Still staged and still hidden; too recent for the sweeper.
    expect(await restarted.staging.sweepAbandonedImports()).toBe(0);
    expect(await census(restarted.pool, projectId, versionId)).toMatchObject({ live_versions: 0, staged_versions: 1 });

    // Past the time-to-live: gone.
    await restarted.pool.query(
      `UPDATE apiome.versions SET import_pending_at = import_pending_at - interval '2 hours' WHERE id = $1`,
      [versionId],
    );
    expect(await restarted.staging.sweepAbandonedImports()).toBe(1);
    expect(await census(restarted.pool, projectId, versionId)).toEqual(NOTHING);
  });

  test('Accept after the sweeper removed the import fails and leaves nothing behind', async () => {
    const { helper, staging, pool } = current;
    const { jobId, status } = await stage(helper, `expired-${RUN}`);
    const { projectId, versionId } = status.result as { projectId: string; versionId: string };
    expect(await staging.sweepAbandonedImports({ ttlMs: 0 })).toBe(1);

    const result = await helper.commitImport(jobId);
    expect(result.success).toBe(false);
    expect(result.error).toContain('no longer awaiting approval');
    expect((await helper.getImportStatus(jobId)).state).toBe('failed');
    expect(await census(pool, projectId, versionId)).toEqual(NOTHING);
    // Reject afterwards is a no-op.
    expect(await helper.rollbackImport(jobId)).toEqual({ success: true });
  });

  test('the sweeper leaves accepted imports and other soft-deleted versions alone', async () => {
    const { helper, staging, pool } = current;
    const { jobId, status } = await stage(helper, `kept-${RUN}`);
    await helper.commitImport(jobId);
    const { projectId, versionId } = status.result as { projectId: string; versionId: string };
    await pool.query('UPDATE apiome.versions SET deleted_at = CURRENT_TIMESTAMP WHERE id = $1', [versionId]);

    expect(await staging.sweepAbandonedImports({ ttlMs: 0 })).toBe(0);
    expect(await census(pool, projectId, versionId)).toMatchObject({ versions: 1, classes: 2 });
  });
});
