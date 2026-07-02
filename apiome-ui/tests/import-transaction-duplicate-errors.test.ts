/**
 * Duplicate-import errors must name the colliding project slug and version id so the user can see
 * exactly what already exists (surfaced to the CLI as `Import failed: [FAILED] <message>`).
 */
import { describe, test, expect, jest } from '@jest/globals';

jest.mock('../lib/db/db', () => ({}));
jest.mock('../lib/db/plan-entitlements', () => ({
  getPlanBlockMessageForNewProject: jest.fn(async () => null),
  getPlanBlockMessageForNewVersion: jest.fn(async () => null),
}));

import { createProjectTx, createVersionTx } from '../lib/db/import-transaction';

/** A PoolClient whose INSERT raises Postgres unique-violation 23505. */
function duplicateClient() {
  return {
    query: jest.fn(async () => {
      const err = new Error('duplicate key value violates unique constraint') as Error & { code: string };
      err.code = '23505';
      throw err;
    }),
  } as never;
}

describe('import duplicate errors name the colliding slug/version', () => {
  test('a duplicate project names the project slug', async () => {
    const res = JSON.parse(
      await createProjectTx(duplicateClient(), 'tenant-1', 'user-1', 'My API', 'desc', 'my-api'),
    );
    expect(res.success).toBe(false);
    expect(res.error).toBe('A project with slug "my-api" already exists in this tenant');
  });

  test('a duplicate version names the version id and project slug', async () => {
    const res = JSON.parse(
      await createVersionTx(duplicateClient(), 'proj-1', 'user-1', '37', 'desc', 'changelog', {
        projectSlug: 'adyen-checkout-api',
      }),
    );
    expect(res.success).toBe(false);
    expect(res.error).toBe('A version with ID "37" already exists in project "adyen-checkout-api"');
  });

  test('a duplicate version without a known project slug still names the version id', async () => {
    const res = JSON.parse(
      await createVersionTx(duplicateClient(), 'proj-1', 'user-1', '37', 'desc', 'changelog'),
    );
    expect(res.success).toBe(false);
    expect(res.error).toBe('A version with ID "37" already exists in this project');
  });
});
