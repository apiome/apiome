/**
 * Unit tests for version tag helpers (lib/db/helper.ts) and version-tag-utils.
 */

import { describe, it, expect, jest, beforeEach } from '@jest/globals';

jest.mock('../../lib/db/db', () => ({
  query: jest.fn(),
}));

jest.mock('bcrypt', () => ({ compare: jest.fn(), hash: jest.fn() }));
jest.mock('crypto', () => ({ randomBytes: jest.fn(() => Buffer.from('test')) }));

jest.mock('next/headers', () => ({
  cookies: jest.fn(() => ({ getAll: () => [] })),
}));

jest.mock('../../lib/db/plan-entitlements', () => ({
  getPlanBlockMessageForNewProject: jest.fn(async () => null),
  getPlanBlockMessageForNewVersion: jest.fn(async () => null),
}));

jest.mock('../../lib/version-merge', () => ({
  mergePreviewFromSpecs: jest.fn(),
}));

jest.mock('../../src/app/utils/openapi', () => ({
  generateOpenApiSpec: jest.fn(() => '{}'),
}));

import { isValidVersionTagName } from '../../lib/version-tag-utils';
import {
  listVersionTags,
  createVersionTag,
  updateVersionTag,
  deleteVersionTag,
} from '../../lib/db/helper';

function getDbMock() {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  return require('../../lib/db/db') as { query: jest.Mock };
}

const PROJECT_ID = 'proj-uuid-1';
const TENANT_ID = 'tenant-uuid-1';
const USER_ID = 'user-uuid-1';
const TAG_ID = 'tag-uuid-1';
const VERSION_ID = 'ver-uuid-1';
const VERSION_ID_2 = 'ver-uuid-2';

describe('isValidVersionTagName', () => {
  it('accepts v1.0 style names', () => {
    expect(isValidVersionTagName('v1.0')).toBe(true);
  });

  it('accepts names starting with a digit', () => {
    expect(isValidVersionTagName('1.0.0-stable')).toBe(true);
  });

  it('rejects empty string', () => {
    expect(isValidVersionTagName('')).toBe(false);
  });

  it('rejects names with spaces', () => {
    expect(isValidVersionTagName('bad name')).toBe(false);
  });
});

describe('listVersionTags', () => {
  beforeEach(() => {
    getDbMock().query.mockClear();
  });

  it('returns success:false when project not in tenant', async () => {
    getDbMock().query.mockResolvedValueOnce({ rowCount: 0, rows: [] });
    const result = JSON.parse(await listVersionTags(PROJECT_ID, TENANT_ID));
    expect(result.success).toBe(false);
  });

  it('returns tags on success', async () => {
    getDbMock().query.mockResolvedValueOnce({ rowCount: 1, rows: [{}] });
    const fakeTag = {
      id: TAG_ID,
      name: 'stable',
      version_id: VERSION_ID,
      target_version_string: '1.0.0',
    };
    getDbMock().query.mockResolvedValueOnce({ rowCount: 1, rows: [fakeTag] });
    const result = JSON.parse(await listVersionTags(PROJECT_ID, TENANT_ID));
    expect(result.success).toBe(true);
    expect(result.tags).toHaveLength(1);
    expect(result.tags[0].name).toBe('stable');
  });
});

describe('createVersionTag', () => {
  beforeEach(() => {
    getDbMock().query.mockClear();
  });

  it('rejects invalid name', async () => {
    const result = JSON.parse(
      await createVersionTag(PROJECT_ID, TENANT_ID, 'bad name', VERSION_ID, USER_ID)
    );
    expect(result.success).toBe(false);
  });

  it('inserts when version exists', async () => {
    getDbMock().query.mockResolvedValueOnce({ rowCount: 1, rows: [{}] });
    getDbMock().query.mockResolvedValueOnce({ rowCount: 1, rows: [{ id: VERSION_ID }] });
    getDbMock().query.mockResolvedValueOnce({
      rowCount: 1,
      rows: [
        {
          id: TAG_ID,
          name: 'v1',
          version_id: VERSION_ID,
          immutable: true,
        },
      ],
    });
    const result = JSON.parse(
      await createVersionTag(PROJECT_ID, TENANT_ID, 'v1', VERSION_ID, USER_ID, { immutable: true })
    );
    expect(result.success).toBe(true);
    expect(result.tag.name).toBe('v1');
  });
});

describe('updateVersionTag', () => {
  beforeEach(() => {
    getDbMock().query.mockClear();
  });

  it('returns TAG_IMMUTABLE when tag is locked', async () => {
    getDbMock().query.mockResolvedValueOnce({ rowCount: 1, rows: [{}] });
    getDbMock().query.mockResolvedValueOnce({
      rowCount: 1,
      rows: [{ id: TAG_ID, immutable: true, protected: false, created_by: USER_ID }],
    });
    const result = JSON.parse(
      await updateVersionTag(TAG_ID, PROJECT_ID, TENANT_ID, USER_ID, true, { versionId: VERSION_ID_2 })
    );
    expect(result.success).toBe(false);
    expect(result.code).toBe('TAG_IMMUTABLE');
  });
});

describe('deleteVersionTag', () => {
  beforeEach(() => {
    getDbMock().query.mockClear();
  });

  it('deletes when allowed', async () => {
    getDbMock().query.mockResolvedValueOnce({ rowCount: 1, rows: [{}] });
    getDbMock().query.mockResolvedValueOnce({
      rowCount: 1,
      rows: [{ immutable: false, protected: false, created_by: USER_ID }],
    });
    getDbMock().query.mockResolvedValueOnce({ rowCount: 1, rows: [] });
    const result = JSON.parse(await deleteVersionTag(TAG_ID, PROJECT_ID, TENANT_ID, USER_ID, false));
    expect(result.success).toBe(true);
  });
});
