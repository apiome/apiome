import { beforeEach, describe, expect, jest, test } from '@jest/globals';

jest.mock('../lib/db/db', () => ({
  query: jest.fn(),
}));

jest.mock('bcrypt', () => ({
  compare: jest.fn(),
  hash: jest.fn(),
}));

jest.mock('crypto', () => ({
  randomBytes: jest.fn(() => Buffer.from('test-api-key-data')),
}));

describe('Database Helper - Named Canvas Layouts', () => {
  let mockQuery: jest.Mock<any>;

  beforeEach(() => {
    const db = require('../lib/db/db');
    mockQuery = db.query as jest.Mock;
    mockQuery.mockReset();
  });

  test('getNamedCanvasLayoutsForVersion deduplicates names and prefers user layouts', async () => {
    const { getNamedCanvasLayoutsForVersion } = await import('../lib/db/helper');

    mockQuery.mockResolvedValue({
      rows: [
        { id: 'u1', name: 'Development Layout', user_id: 'user-1' },
        { id: 's1', name: 'Development Layout', user_id: null },
        { id: 's2', name: 'Presentation Layout', user_id: null },
      ]
    });

    const result = await getNamedCanvasLayoutsForVersion('version-1', 'user-1');
    const parsed = JSON.parse(result);

    expect(parsed.success).toBe(true);
    expect(parsed.layouts).toHaveLength(2);
    expect(parsed.layouts[0].name).toBe('Development Layout');
    expect(parsed.layouts[0].id).toBe('u1');
    expect(mockQuery).toHaveBeenCalledWith(
      expect.stringContaining('ORDER BY name ASC, (user_id = $2) DESC NULLS LAST, updated_at DESC'),
      ['version-1', 'user-1']
    );
  });

  test('getNamedCanvasLayoutsForVersion normalizes whitespace before de-duplication', async () => {
    const { getNamedCanvasLayoutsForVersion } = await import('../lib/db/helper');

    mockQuery.mockResolvedValue({
      rows: [
        { id: 'u1', name: '  Development Layout  ', user_id: 'user-1' },
        { id: 's1', name: 'Development Layout', user_id: null },
        { id: 's2', name: '   ', user_id: null },
      ]
    });

    const result = await getNamedCanvasLayoutsForVersion('version-1', 'user-1');
    const parsed = JSON.parse(result);

    expect(parsed.success).toBe(true);
    expect(parsed.layouts).toHaveLength(1);
    expect(parsed.layouts[0].id).toBe('u1');
    expect(parsed.layouts[0].name).toBe('Development Layout');
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

  test('saveNamedCanvasLayout updates existing named layout', async () => {
    const { saveNamedCanvasLayout } = await import('../lib/db/helper');

    mockQuery
      .mockResolvedValueOnce({ rowCount: 1, rows: [{ id: 'layout-1' }] }) // existing lookup
      .mockResolvedValueOnce({ rowCount: 1, rows: [{ version_id: 'version-1', user_id: 'user-1' }] }) // update lookup
      .mockResolvedValueOnce({ rowCount: 1, rows: [{ id: 'layout-1', name: 'Dependency Layout' }] }); // update return

    const result = await saveNamedCanvasLayout(
      'version-1',
      'user-1',
      'Dependency Layout',
      { x: 0, y: 0, zoom: 1 },
      [{ id: 'node-1', type: 'classNode', position: { x: 1, y: 2 } }],
      []
    );
    const parsed = JSON.parse(result);

    expect(parsed.success).toBe(true);
    expect(parsed.layout.id).toBe('layout-1');
  });

  test('saveNamedCanvasLayout creates layout when missing', async () => {
    const { saveNamedCanvasLayout } = await import('../lib/db/helper');

    mockQuery
      .mockResolvedValueOnce({ rowCount: 0, rows: [] }) // existing lookup
      .mockResolvedValueOnce({ rowCount: 1, rows: [{ id: 'layout-2', name: 'Presentation Layout' }] }); // create return

    const result = await saveNamedCanvasLayout(
      'version-1',
      'user-1',
      'Presentation Layout',
      { x: 0, y: 0, zoom: 1 },
      [{ id: 'node-1', type: 'classNode', position: { x: 1, y: 2 } }],
      []
    );
    const parsed = JSON.parse(result);

    expect(parsed.success).toBe(true);
    expect(parsed.layout.name).toBe('Presentation Layout');
  });

  test('saveNamedCanvasLayout rejects blank layout name after trim', async () => {
    const { saveNamedCanvasLayout } = await import('../lib/db/helper');

    const result = await saveNamedCanvasLayout(
      'version-1',
      'user-1',
      '   ',
      { x: 0, y: 0, zoom: 1 },
      [{ id: 'node-1', type: 'classNode', position: { x: 1, y: 2 } }],
      []
    );
    const parsed = JSON.parse(result);

    expect(parsed.success).toBe(false);
    expect(parsed.error).toBe('Layout name is required');
    expect(mockQuery).not.toHaveBeenCalled();
  });

  test('saveNamedCanvasLayout creates shared layout when userId is null and trims name', async () => {
    const { saveNamedCanvasLayout } = await import('../lib/db/helper');

    mockQuery
      .mockResolvedValueOnce({ rowCount: 0, rows: [] }) // existing lookup
      .mockResolvedValueOnce({ rowCount: 1, rows: [{ id: 'layout-shared-1', name: 'Shared Layout' }] }); // create return

    const result = await saveNamedCanvasLayout(
      'version-1',
      null,
      '  Shared Layout  ',
      { x: 0, y: 0, zoom: 1 },
      [{ id: 'node-1', type: 'classNode', position: { x: 1, y: 2 } }],
      []
    );
    const parsed = JSON.parse(result);

    expect(parsed.success).toBe(true);
    expect(parsed.layout.id).toBe('layout-shared-1');

    expect(mockQuery).toHaveBeenNthCalledWith(
      1,
      expect.stringContaining('user_id IS NOT DISTINCT FROM $3'),
      ['version-1', 'Shared Layout', null]
    );
    expect(mockQuery).toHaveBeenNthCalledWith(
      2,
      expect.stringContaining('INSERT INTO odb.canvas_layouts'),
      expect.arrayContaining(['version-1', null, 'Shared Layout'])
    );
  });

  test('saveNamedCanvasLayout updates existing shared layout when userId is null', async () => {
    const { saveNamedCanvasLayout } = await import('../lib/db/helper');

    mockQuery
      .mockResolvedValueOnce({ rowCount: 1, rows: [{ id: 'layout-shared-1' }] }) // existing lookup
      .mockResolvedValueOnce({ rowCount: 1, rows: [{ version_id: 'version-1', user_id: null }] }) // update lookup
      .mockResolvedValueOnce({ rowCount: 1, rows: [{ id: 'layout-shared-1', name: 'Shared Layout' }] }); // update return

    const result = await saveNamedCanvasLayout(
      'version-1',
      null,
      'Shared Layout',
      { x: 0, y: 0, zoom: 1 },
      [{ id: 'node-1', type: 'classNode', position: { x: 1, y: 2 } }],
      []
    );
    const parsed = JSON.parse(result);

    expect(parsed.success).toBe(true);
    expect(parsed.layout.id).toBe('layout-shared-1');
    expect(mockQuery).toHaveBeenNthCalledWith(
      1,
      expect.stringContaining('user_id IS NOT DISTINCT FROM $3'),
      ['version-1', 'Shared Layout', null]
    );
  });
});
