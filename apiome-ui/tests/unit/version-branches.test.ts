/**
 * Unit tests for version branch helper functions in lib/db/helper.ts.
 * Merge preview/apply is covered by apiome-rest (#738).
 */

import { describe, it, expect, jest, beforeEach } from '@jest/globals';

// Mock DB pool
jest.mock('../../lib/db/db', () => ({
  query: jest.fn(),
}));

// Mock bcrypt and crypto (required by helper.ts)
jest.mock('bcrypt', () => ({ compare: jest.fn(), hash: jest.fn() }));
jest.mock('crypto', () => ({ randomBytes: jest.fn(() => Buffer.from('test')) }));

// Mock Next.js server-only headers
jest.mock('next/headers', () => ({
  cookies: jest.fn(() => ({ getAll: () => [] })),
}));

// Mock plan entitlements
jest.mock('../../lib/db/plan-entitlements', () => ({
  getPlanBlockMessageForNewProject: jest.fn(async () => null),
  getPlanBlockMessageForNewVersion: jest.fn(async () => null),
}));

// Mock OpenAPI generation used by buildOpenApiSpecJsonForVersion
jest.mock('../../src/app/utils/openapi', () => ({
  generateOpenApiSpec: jest.fn(() => '{}'),
}));

import { isValidVersionBranchName, suggestBranchNameFromRevision } from '../../lib/version-branch-utils';
import {
  listVersionBranches,
  createVersionBranch,
  deleteVersionBranch,
  updateVersionBranchProtection,
  setVersionRevisionLock,
} from '../../lib/db/helper';

// ─── helpers ─────────────────────────────────────────────────────────────────

function getDbMock() {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  return require('../../lib/db/db') as { query: jest.Mock };
}

const PROJECT_ID = 'proj-uuid-1';
const TENANT_ID = 'tenant-uuid-1';
const USER_ID = 'user-uuid-1';
const BRANCH_ID = 'branch-uuid-1';
const VERSION_ID = 'ver-uuid-1';
const VERSION_ID_2 = 'ver-uuid-2';

// ─── isValidVersionBranchName ─────────────────────────────────────────────────

describe('isValidVersionBranchName', () => {
  it('accepts simple alpha name', () => {
    expect(isValidVersionBranchName('main')).toBe(true);
  });

  it('accepts names with digits, dots, dashes and slashes', () => {
    expect(isValidVersionBranchName('feature/my-branch.1')).toBe(true);
  });

  it('rejects names starting with a digit', () => {
    expect(isValidVersionBranchName('1-bad')).toBe(false);
  });

  it('rejects empty string', () => {
    expect(isValidVersionBranchName('')).toBe(false);
  });

  it('rejects names with spaces', () => {
    expect(isValidVersionBranchName('bad name')).toBe(false);
  });

  it('rejects names longer than 255 chars', () => {
    expect(isValidVersionBranchName('a' + 'x'.repeat(255))).toBe(false);
  });

  it('accepts exactly 255-char name', () => {
    expect(isValidVersionBranchName('a' + 'x'.repeat(254))).toBe(true);
  });
});

// ─── suggestBranchNameFromRevision (#2571) ─────────────────────────────────────

describe('suggestBranchNameFromRevision', () => {
  it('builds feature/ slug from short message', () => {
    expect(suggestBranchNameFromRevision('Add enums API', '1.0.0')).toBe('feature/add-enums-api');
  });

  it('falls back to branch/v semver when message is empty', () => {
    expect(suggestBranchNameFromRevision('', '2.3.4')).toBe('branch/v2-3-4');
  });

  it('falls back when message yields no usable slug', () => {
    expect(suggestBranchNameFromRevision('---', '0.1.0')).toBe('branch/v0-1-0');
  });
});

// ─── listVersionBranches ─────────────────────────────────────────────────────

describe('listVersionBranches', () => {
  beforeEach(() => {
    getDbMock().query.mockClear();
  });

  it('returns success:false when project not in tenant', async () => {
    getDbMock().query.mockResolvedValueOnce({ rowCount: 0, rows: [] });
    const result = JSON.parse(await listVersionBranches(PROJECT_ID, TENANT_ID));
    expect(result.success).toBe(false);
    expect(result.error).toMatch(/not found/i);
  });

  it('returns branch list on success', async () => {
    // assertProjectInTenant → 1 row
    getDbMock().query.mockResolvedValueOnce({ rowCount: 1, rows: [{}] });
    // list query → branches
    const fakeBranch = {
      id: BRANCH_ID,
      project_id: PROJECT_ID,
      name: 'main',
      tip_version_id: VERSION_ID,
      tip_version_string: '1.0.0',
    };
    getDbMock().query.mockResolvedValueOnce({ rowCount: 1, rows: [fakeBranch] });

    const result = JSON.parse(await listVersionBranches(PROJECT_ID, TENANT_ID));
    expect(result.success).toBe(true);
    expect(result.branches).toHaveLength(1);
    expect(result.branches[0].name).toBe('main');
  });

  it('uses AND v.project_id = b.project_id in the JOIN', async () => {
    getDbMock().query.mockResolvedValueOnce({ rowCount: 1, rows: [{}] });
    getDbMock().query.mockResolvedValueOnce({ rowCount: 0, rows: [] });
    await listVersionBranches(PROJECT_ID, TENANT_ID);
    const listCall = getDbMock().query.mock.calls[1];
    expect((listCall[0] as string).toLowerCase()).toContain('v.project_id = b.project_id');
  });

  it('returns success:false on DB error', async () => {
    getDbMock().query.mockResolvedValueOnce({ rowCount: 1, rows: [{}] });
    getDbMock().query.mockRejectedValueOnce(new Error('DB down'));
    const result = JSON.parse(await listVersionBranches(PROJECT_ID, TENANT_ID));
    expect(result.success).toBe(false);
    expect(result.error).toMatch(/DB down/);
  });
});

// ─── createVersionBranch ─────────────────────────────────────────────────────

describe('createVersionBranch', () => {
  beforeEach(() => {
    getDbMock().query.mockClear();
  });

  it('rejects invalid branch name', async () => {
    const result = JSON.parse(
      await createVersionBranch(PROJECT_ID, TENANT_ID, '123bad', VERSION_ID, USER_ID)
    );
    expect(result.success).toBe(false);
    expect(result.error).toMatch(/letter/i);
  });

  it('returns success:false when project not in tenant', async () => {
    getDbMock().query.mockResolvedValueOnce({ rowCount: 0, rows: [] });
    const result = JSON.parse(
      await createVersionBranch(PROJECT_ID, TENANT_ID, 'feature', VERSION_ID, USER_ID)
    );
    expect(result.success).toBe(false);
    expect(result.error).toMatch(/not found/i);
  });

  it('returns success:false when source version not found', async () => {
    getDbMock().query.mockResolvedValueOnce({ rowCount: 1, rows: [{}] }); // project OK
    getDbMock().query.mockResolvedValueOnce({ rowCount: 0, rows: [] });    // version missing
    const result = JSON.parse(
      await createVersionBranch(PROJECT_ID, TENANT_ID, 'feature', VERSION_ID, USER_ID)
    );
    expect(result.success).toBe(false);
    expect(result.error).toMatch(/version not found/i);
  });

  it('creates branch and returns success', async () => {
    getDbMock().query.mockResolvedValueOnce({ rowCount: 1, rows: [{}] }); // project OK
    getDbMock().query.mockResolvedValueOnce({ rowCount: 1, rows: [{ id: VERSION_ID }] }); // version found
    const fakeBranch = { id: BRANCH_ID, name: 'feature', tip_version_id: VERSION_ID };
    getDbMock().query.mockResolvedValueOnce({ rowCount: 1, rows: [fakeBranch] }); // insert
    const result = JSON.parse(
      await createVersionBranch(PROJECT_ID, TENANT_ID, 'feature', VERSION_ID, USER_ID)
    );
    expect(result.success).toBe(true);
    expect(result.branch.name).toBe('feature');
  });

  it('returns duplicate error on unique constraint violation', async () => {
    getDbMock().query.mockResolvedValueOnce({ rowCount: 1, rows: [{}] });
    getDbMock().query.mockResolvedValueOnce({ rowCount: 1, rows: [{ id: VERSION_ID }] });
    const pgError = Object.assign(new Error('duplicate key'), { code: '23505' });
    getDbMock().query.mockRejectedValueOnce(pgError);
    const result = JSON.parse(
      await createVersionBranch(PROJECT_ID, TENANT_ID, 'feature', VERSION_ID, USER_ID)
    );
    expect(result.success).toBe(false);
    expect(result.error).toMatch(/already exists/i);
  });
});

// ─── deleteVersionBranch ─────────────────────────────────────────────────────

describe('deleteVersionBranch', () => {
  beforeEach(() => {
    getDbMock().query.mockClear();
  });

  it('returns success:false when project not in tenant', async () => {
    getDbMock().query.mockResolvedValueOnce({ rowCount: 0, rows: [] });
    const result = JSON.parse(
      await deleteVersionBranch(BRANCH_ID, PROJECT_ID, TENANT_ID, USER_ID, false)
    );
    expect(result.success).toBe(false);
    expect(result.error).toMatch(/not found/i);
  });

  it('returns success:false when branch not found', async () => {
    getDbMock().query.mockResolvedValueOnce({ rowCount: 1, rows: [{}] }); // project OK
    getDbMock().query.mockResolvedValueOnce({ rowCount: 0, rows: [] });    // branch missing
    const result = JSON.parse(
      await deleteVersionBranch(BRANCH_ID, PROJECT_ID, TENANT_ID, USER_ID, false)
    );
    expect(result.success).toBe(false);
    expect(result.error).toMatch(/not found/i);
  });

  it('returns BRANCH_PROTECTED when branch is protected and user is not admin', async () => {
    getDbMock().query.mockResolvedValueOnce({ rowCount: 1, rows: [{}] });
    getDbMock().query.mockResolvedValueOnce({
      rowCount: 1,
      rows: [
        {
          id: BRANCH_ID,
          created_by: USER_ID,
          protected: true,
          name: 'feature',
          is_default: false,
        },
      ],
    });
    getDbMock().query.mockResolvedValueOnce({ rowCount: 1 });
    const result = JSON.parse(
      await deleteVersionBranch(BRANCH_ID, PROJECT_ID, TENANT_ID, USER_ID, false)
    );
    expect(result.success).toBe(false);
    expect(result.code).toBe('BRANCH_PROTECTED');
  });

  it('returns unauthorized when non-creator non-admin tries to delete', async () => {
    getDbMock().query.mockResolvedValueOnce({ rowCount: 1, rows: [{}] }); // project OK
    getDbMock().query.mockResolvedValueOnce({
      rowCount: 1,
      rows: [
        {
          id: BRANCH_ID,
          created_by: 'other-user',
          protected: false,
          name: 'feature',
          is_default: false,
        },
      ],
    });
    const result = JSON.parse(
      await deleteVersionBranch(BRANCH_ID, PROJECT_ID, TENANT_ID, USER_ID, false)
    );
    expect(result.success).toBe(false);
    expect(result.error).toMatch(/creator|admin/i);
  });

  it('allows tenant admin to delete any branch', async () => {
    getDbMock().query.mockResolvedValueOnce({ rowCount: 1, rows: [{}] });
    getDbMock().query.mockResolvedValueOnce({
      rowCount: 1,
      rows: [
        {
          id: BRANCH_ID,
          created_by: 'other-user',
          protected: false,
          name: 'feature',
          is_default: false,
        },
      ],
    });
    getDbMock().query.mockResolvedValueOnce({ rowCount: 1, rows: [] }); // DELETE
    const result = JSON.parse(
      await deleteVersionBranch(BRANCH_ID, PROJECT_ID, TENANT_ID, USER_ID, true)
    );
    expect(result.success).toBe(true);
  });

  it('allows creator to delete their own branch', async () => {
    getDbMock().query.mockResolvedValueOnce({ rowCount: 1, rows: [{}] });
    getDbMock().query.mockResolvedValueOnce({
      rowCount: 1,
      rows: [
        {
          id: BRANCH_ID,
          created_by: USER_ID,
          protected: false,
          name: 'feature',
          is_default: false,
        },
      ],
    });
    getDbMock().query.mockResolvedValueOnce({ rowCount: 1, rows: [] });
    const result = JSON.parse(
      await deleteVersionBranch(BRANCH_ID, PROJECT_ID, TENANT_ID, USER_ID, false)
    );
    expect(result.success).toBe(true);
  });

  it('returns BRANCH_DELETE_FORBIDDEN for main even for tenant admin', async () => {
    getDbMock().query.mockResolvedValueOnce({ rowCount: 1, rows: [{}] });
    getDbMock().query.mockResolvedValueOnce({
      rowCount: 1,
      rows: [
        {
          id: BRANCH_ID,
          created_by: USER_ID,
          protected: false,
          name: 'main',
          is_default: false,
        },
      ],
    });
    const result = JSON.parse(
      await deleteVersionBranch(BRANCH_ID, PROJECT_ID, TENANT_ID, USER_ID, true)
    );
    expect(result.success).toBe(false);
    expect(result.code).toBe('BRANCH_DELETE_FORBIDDEN');
    expect(result.error).toMatch(/main/i);
  });

  it('returns BRANCH_DELETE_FORBIDDEN for default branch even for tenant admin', async () => {
    getDbMock().query.mockResolvedValueOnce({ rowCount: 1, rows: [{}] });
    getDbMock().query.mockResolvedValueOnce({
      rowCount: 1,
      rows: [
        {
          id: BRANCH_ID,
          created_by: USER_ID,
          protected: false,
          name: 'trunk',
          is_default: true,
        },
      ],
    });
    const result = JSON.parse(
      await deleteVersionBranch(BRANCH_ID, PROJECT_ID, TENANT_ID, USER_ID, true)
    );
    expect(result.success).toBe(false);
    expect(result.code).toBe('BRANCH_DELETE_FORBIDDEN');
    expect(result.error).toMatch(/default/i);
  });
});

// ─── updateVersionBranchProtection ───────────────────────────────────────────

describe('updateVersionBranchProtection', () => {
  beforeEach(() => {
    getDbMock().query.mockClear();
  });

  it('returns FORBIDDEN when caller is not a tenant admin', async () => {
    const result = JSON.parse(
      await updateVersionBranchProtection(BRANCH_ID, PROJECT_ID, TENANT_ID, USER_ID, false, true)
    );
    expect(result.success).toBe(false);
    expect(result.code).toBe('FORBIDDEN');
  });

  it('returns success:false when project not in tenant', async () => {
    getDbMock().query.mockResolvedValueOnce({ rowCount: 0, rows: [] }); // assertProjectInTenant → not found
    const result = JSON.parse(
      await updateVersionBranchProtection(BRANCH_ID, PROJECT_ID, TENANT_ID, USER_ID, true, true)
    );
    expect(result.success).toBe(false);
    expect(result.error).toMatch(/not found/i);
  });

  it('returns success:false when branch not found', async () => {
    getDbMock().query.mockResolvedValueOnce({ rowCount: 1, rows: [{}] }); // assertProjectInTenant → OK
    getDbMock().query.mockResolvedValueOnce({ rowCount: 0, rows: [] });   // UPDATE → 0 rows
    const result = JSON.parse(
      await updateVersionBranchProtection(BRANCH_ID, PROJECT_ID, TENANT_ID, USER_ID, true, true)
    );
    expect(result.success).toBe(false);
    expect(result.error).toMatch(/not found/i);
  });

  it('updates protection and returns success when admin', async () => {
    const fakeBranch = {
      id: BRANCH_ID,
      project_id: PROJECT_ID,
      name: 'main',
      tip_version_id: VERSION_ID,
      protected: true,
      created_by: USER_ID,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };
    getDbMock().query.mockResolvedValueOnce({ rowCount: 1, rows: [{}] });          // assertProjectInTenant
    getDbMock().query.mockResolvedValueOnce({ rowCount: 1, rows: [fakeBranch] });  // UPDATE
    getDbMock().query.mockResolvedValueOnce({ rowCount: 1, rows: [] });            // audit INSERT
    const result = JSON.parse(
      await updateVersionBranchProtection(BRANCH_ID, PROJECT_ID, TENANT_ID, USER_ID, true, true)
    );
    expect(result.success).toBe(true);
    expect(result.branch.protected).toBe(true);
  });

  it('writes an audit row on successful policy change', async () => {
    const fakeBranch = { id: BRANCH_ID, protected: false };
    getDbMock().query.mockResolvedValueOnce({ rowCount: 1, rows: [{}] });
    getDbMock().query.mockResolvedValueOnce({ rowCount: 1, rows: [fakeBranch] });
    getDbMock().query.mockResolvedValueOnce({ rowCount: 1, rows: [] }); // audit
    await updateVersionBranchProtection(BRANCH_ID, PROJECT_ID, TENANT_ID, USER_ID, true, false);
    // Three queries expected: assertProjectInTenant, UPDATE, audit INSERT
    expect(getDbMock().query).toHaveBeenCalledTimes(3);
  });

  it('updates requireMergePath without protected and returns success', async () => {
    const fakeBranch = {
      id: BRANCH_ID,
      project_id: PROJECT_ID,
      name: 'main',
      tip_version_id: VERSION_ID,
      protected: false,
      require_merge_path: true,
      created_by: USER_ID,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };
    getDbMock().query.mockResolvedValueOnce({ rowCount: 1, rows: [{}] });         // assertProjectInTenant
    getDbMock().query.mockResolvedValueOnce({ rowCount: 1, rows: [fakeBranch] }); // UPDATE
    getDbMock().query.mockResolvedValueOnce({ rowCount: 1, rows: [] });           // audit INSERT
    // Pass undefined for branchProtected, true for requireMergePath
    const result = JSON.parse(
      await updateVersionBranchProtection(BRANCH_ID, PROJECT_ID, TENANT_ID, USER_ID, true, undefined, true)
    );
    expect(result.success).toBe(true);
    expect(result.branch.require_merge_path).toBe(true);
  });

  it('returns INVALID_INPUT when both protected and requireMergePath are omitted', async () => {
    // Even as a tenant admin, omitting both fields should return INVALID_INPUT (no DB call)
    const result = JSON.parse(
      await updateVersionBranchProtection(BRANCH_ID, PROJECT_ID, TENANT_ID, USER_ID, true, undefined, undefined)
    );
    expect(result.success).toBe(false);
    expect(result.code).toBe('INVALID_INPUT');
    expect(getDbMock().query).not.toHaveBeenCalled();
  });
});

// ─── setVersionRevisionLock ───────────────────────────────────────────────────

const VERSION_RECORD_ID = 'ver-record-uuid-1';

describe('setVersionRevisionLock', () => {
  beforeEach(() => {
    getDbMock().query.mockClear();
  });

  it('returns FORBIDDEN when caller is not a tenant admin', async () => {
    const result = JSON.parse(
      await setVersionRevisionLock(VERSION_RECORD_ID, PROJECT_ID, TENANT_ID, USER_ID, false, true)
    );
    expect(result.success).toBe(false);
    expect(result.code).toBe('FORBIDDEN');
  });

  it('returns success:false when project not in tenant', async () => {
    getDbMock().query.mockResolvedValueOnce({ rowCount: 0, rows: [] }); // assertProjectInTenant → not found
    const result = JSON.parse(
      await setVersionRevisionLock(VERSION_RECORD_ID, PROJECT_ID, TENANT_ID, USER_ID, true, true)
    );
    expect(result.success).toBe(false);
    expect(result.error).toMatch(/not found/i);
  });

  it('returns success:false when version not found', async () => {
    getDbMock().query.mockResolvedValueOnce({ rowCount: 1, rows: [{}] }); // assertProjectInTenant → OK
    getDbMock().query.mockResolvedValueOnce({ rowCount: 0, rows: [] });   // UPDATE → 0 rows
    const result = JSON.parse(
      await setVersionRevisionLock(VERSION_RECORD_ID, PROJECT_ID, TENANT_ID, USER_ID, true, true)
    );
    expect(result.success).toBe(false);
    expect(result.error).toMatch(/not found/i);
  });

  it('locks a revision and returns success when admin', async () => {
    const fakeVersion = {
      id: VERSION_RECORD_ID,
      project_id: PROJECT_ID,
      version_id: '1.0.0',
      revision_locked: true,
    };
    getDbMock().query.mockResolvedValueOnce({ rowCount: 1, rows: [{}] });            // assertProjectInTenant
    getDbMock().query.mockResolvedValueOnce({ rowCount: 1, rows: [fakeVersion] });   // UPDATE
    getDbMock().query.mockResolvedValueOnce({ rowCount: 1, rows: [] });              // audit INSERT
    const result = JSON.parse(
      await setVersionRevisionLock(VERSION_RECORD_ID, PROJECT_ID, TENANT_ID, USER_ID, true, true)
    );
    expect(result.success).toBe(true);
    expect(result.version.revision_locked).toBe(true);
  });

  it('unlocks a revision and returns success when admin', async () => {
    const fakeVersion = {
      id: VERSION_RECORD_ID,
      project_id: PROJECT_ID,
      version_id: '1.0.0',
      revision_locked: false,
    };
    getDbMock().query.mockResolvedValueOnce({ rowCount: 1, rows: [{}] });
    getDbMock().query.mockResolvedValueOnce({ rowCount: 1, rows: [fakeVersion] });
    getDbMock().query.mockResolvedValueOnce({ rowCount: 1, rows: [] });
    const result = JSON.parse(
      await setVersionRevisionLock(VERSION_RECORD_ID, PROJECT_ID, TENANT_ID, USER_ID, true, false)
    );
    expect(result.success).toBe(true);
    expect(result.version.revision_locked).toBe(false);
  });

  it('writes an audit row on successful lock change', async () => {
    const fakeVersion = { id: VERSION_RECORD_ID, revision_locked: true };
    getDbMock().query.mockResolvedValueOnce({ rowCount: 1, rows: [{}] });
    getDbMock().query.mockResolvedValueOnce({ rowCount: 1, rows: [fakeVersion] });
    getDbMock().query.mockResolvedValueOnce({ rowCount: 1, rows: [] }); // audit
    await setVersionRevisionLock(VERSION_RECORD_ID, PROJECT_ID, TENANT_ID, USER_ID, true, true);
    // Three queries expected: assertProjectInTenant, UPDATE, audit INSERT
    expect(getDbMock().query).toHaveBeenCalledTimes(3);
  });
});
