import { beforeEach, describe, expect, jest, test } from '@jest/globals';

jest.mock('../lib/db/db', () => {
  const query = jest.fn();
  return {
    query,
    connect: jest.fn(async () => ({
      query,
      release: jest.fn(),
    })),
  };
});

jest.mock('bcrypt', () => ({
  compare: jest.fn(),
  hash: jest.fn(),
}));

jest.mock('crypto', () => ({
  randomBytes: jest.fn(() => Buffer.from('test-api-key-data')),
}));

describe('Database Helper - Named Canvas Layouts', () => {
  let mockQuery: jest.Mock<any>;
  let mockGetAuthSession: jest.Mock<any>;

  beforeEach(() => {
    const db = require('../lib/db/db');
    mockQuery = db.query as jest.Mock;
    mockQuery.mockReset();

    const serverSession = require('../lib/auth/server-session');
    mockGetAuthSession = serverSession.getAuthSession as jest.Mock<any>;
    mockGetAuthSession.mockReset();
    mockGetAuthSession.mockResolvedValue({
      user: { user_id: 'user-1', current_tenant_id: 'tenant-1' },
    });
  });

  test('getNamedCanvasLayout returns null when no named layout exists', async () => {
    const { getNamedCanvasLayout } = await import('../lib/db/helper');

    mockQuery.mockResolvedValue({ rowCount: 0, rows: [] });

    const result = await getNamedCanvasLayout('version-1', 'user-1', 'Logical Layout');
    const parsed = JSON.parse(result);

    expect(parsed.success).toBe(true);
    expect(parsed.layout).toBeNull();
  });

  test('getNamedCanvasLayout trims requested name before querying', async () => {
    const { getNamedCanvasLayout } = await import('../lib/db/helper');

    mockQuery.mockResolvedValue({
      rowCount: 1,
      rows: [{ id: 'layout-1', name: 'Development Layout' }]
    });

    const result = await getNamedCanvasLayout('version-1', 'user-1', '  Development Layout  ');
    const parsed = JSON.parse(result);

    expect(parsed.success).toBe(true);
    expect(parsed.layout.id).toBe('layout-1');
    expect(mockQuery).toHaveBeenCalledWith(
      expect.stringContaining('ORDER BY (user_id = $3) DESC NULLS LAST, updated_at DESC'),
      ['version-1', 'Development Layout', 'user-1']
    );
  });

  test('getNamedCanvasLayout returns null for blank name after trim', async () => {
    const { getNamedCanvasLayout } = await import('../lib/db/helper');

    const result = await getNamedCanvasLayout('version-1', 'user-1', '   ');
    const parsed = JSON.parse(result);

    expect(parsed.success).toBe(true);
    expect(parsed.layout).toBeNull();
    expect(mockQuery).not.toHaveBeenCalled();
  });

});

describe('Database Helper - default named canvas layout preference', () => {
  let mockQuery: jest.Mock<any>;
  let mockGetAuthSession: jest.Mock<any>;

  beforeEach(() => {
    const db = require('../lib/db/db');
    mockQuery = db.query as jest.Mock;
    mockQuery.mockReset();

    // Default session for this describe block: authenticated as user-1
    const serverSession = require('../lib/auth/server-session');
    mockGetAuthSession = serverSession.getAuthSession as jest.Mock<any>;
    mockGetAuthSession.mockReset();
    mockGetAuthSession.mockResolvedValue({
      user: { user_id: 'user-1', current_tenant_id: 'tenant-1' },
    });
  });

  test('getEffectiveDefaultLayoutName returns user default when present', async () => {
    const { getEffectiveDefaultLayoutName } = await import('../lib/db/helper');

    mockQuery.mockResolvedValueOnce({
      rowCount: 1,
      rows: [{ layout_name: '  Presentation Layout  ' }]
    });

    const result = await getEffectiveDefaultLayoutName('version-1', 'user-1', 'tenant-1');
    const parsed = JSON.parse(result);

    expect(parsed.success).toBe(true);
    expect(parsed.layoutName).toBe('Presentation Layout');
    expect(mockQuery).toHaveBeenCalledTimes(1);
  });

  test('getEffectiveDefaultLayoutName falls back to tenant when user has no row', async () => {
    const { getEffectiveDefaultLayoutName } = await import('../lib/db/helper');

    mockQuery
      .mockResolvedValueOnce({ rowCount: 0, rows: [] })
      .mockResolvedValueOnce({ rowCount: 1, rows: [{ layout_name: 'Logical Layout' }] });

    const result = await getEffectiveDefaultLayoutName('version-1', 'user-1', 'tenant-1');
    const parsed = JSON.parse(result);

    expect(parsed.success).toBe(true);
    expect(parsed.layoutName).toBe('Logical Layout');
  });

  test('getEffectiveDefaultLayoutName uses built-in fallback when no preferences', async () => {
    const { getEffectiveDefaultLayoutName } = await import('../lib/db/helper');

    mockQuery
      .mockResolvedValueOnce({ rowCount: 0, rows: [] })
      .mockResolvedValueOnce({ rowCount: 0, rows: [] });

    const result = await getEffectiveDefaultLayoutName('version-1', 'user-1', 'tenant-1');
    const parsed = JSON.parse(result);

    expect(parsed.success).toBe(true);
    expect(parsed.layoutName).toBe('Development Layout');
  });

  test('isTenantAdmin returns false when unauthenticated', async () => {
    mockGetAuthSession.mockResolvedValueOnce(null);

    const { isTenantAdmin } = await import('../lib/db/helper');

    const result = await isTenantAdmin('tenant-1');
    const parsed = JSON.parse(result);

    expect(parsed.success).toBe(true);
    expect(parsed.isAdmin).toBe(false);
    expect(mockQuery).not.toHaveBeenCalled();
  });

  test('isTenantAdmin returns true for authenticated admin', async () => {
    const { isTenantAdmin } = await import('../lib/db/helper');

    mockQuery.mockResolvedValueOnce({ rowCount: 1, rows: [{ '?column?': 1 }] });

    const result = await isTenantAdmin('tenant-1');
    const parsed = JSON.parse(result);

    expect(parsed.success).toBe(true);
    expect(parsed.isAdmin).toBe(true);
    expect(mockQuery).toHaveBeenCalledWith(
      expect.stringContaining('tenant_administrators'),
      ['tenant-1', 'user-1']
    );
  });

  test('getClassIdsForVersion returns ids for non-deleted classes in version', async () => {
    const { getClassIdsForVersion } = await import('../lib/db/helper');

    mockQuery.mockResolvedValueOnce({
      rows: [{ id: 'class-a' }, { id: 'class-b' }],
    });

    const result = await getClassIdsForVersion('version-1');
    const parsed = JSON.parse(result);

    expect(parsed.success).toBe(true);
    expect(parsed.classIds).toEqual(['class-a', 'class-b']);
    expect(mockQuery).toHaveBeenCalledWith(
      expect.stringContaining('FROM apiome.classes'),
      ['version-1']
    );
  });
});
