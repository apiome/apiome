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

  test('getNamedCanvasLayoutsForVersion includes stored layout annotations metadata', async () => {
    const { getNamedCanvasLayoutsForVersion } = await import('../lib/db/helper');

    mockQuery.mockResolvedValue({
      rows: [
        {
          id: 'u1',
          name: 'Development Layout',
          user_id: 'user-1',
          metadata: { comment: 'Review', annotations: 'Keep service nodes grouped.' },
        },
      ],
    });

    const result = await getNamedCanvasLayoutsForVersion('version-1', 'user-1');
    const parsed = JSON.parse(result);

    expect(parsed.success).toBe(true);
    expect(parsed.layouts).toHaveLength(1);
    expect(parsed.layouts[0].metadata).toEqual({
      comment: 'Review',
      annotations: 'Keep service nodes grouped.',
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

  test('saveNamedCanvasLayout updates existing named layout', async () => {
    const { saveNamedCanvasLayout } = await import('../lib/db/helper');

    mockQuery
      .mockResolvedValueOnce({ rowCount: 1, rows: [{ id: 'layout-1' }] }) // existing lookup (pool)
      .mockResolvedValueOnce({ rowCount: 0 }) // BEGIN
      .mockResolvedValueOnce({
        rowCount: 1,
        rows: [
          {
            version_id: 'version-1',
            user_id: 'user-1',
            viewport: { x: 0, y: 0, zoom: 1 },
            nodes: [],
            edges: [],
            grid_settings: {},
            minimap_settings: {}
          }
        ]
      }) // SELECT FOR UPDATE
      .mockResolvedValueOnce({ rows: [{ n: 0 }] }) // max revision
      .mockResolvedValueOnce({ rowCount: 1 }) // insert revision
      .mockResolvedValueOnce({ rowCount: 0 }) // prune old revisions
      .mockResolvedValueOnce({ rowCount: 1, rows: [{ id: 'layout-1', name: 'Dependency Layout' }] }) // UPDATE RETURNING
      .mockResolvedValueOnce({ rowCount: 0 }); // COMMIT

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

  test('saveNamedCanvasLayout stores comment and annotations in metadata on create', async () => {
    const { saveNamedCanvasLayout } = await import('../lib/db/helper');

    mockQuery
      .mockResolvedValueOnce({ rowCount: 0, rows: [] }) // existing lookup
      .mockResolvedValueOnce({ rowCount: 1, rows: [{ id: 'layout-3', name: 'Annotated Layout' }] }); // create return

    const result = await saveNamedCanvasLayout(
      'version-1',
      'user-1',
      'Annotated Layout',
      { x: 0, y: 0, zoom: 1 },
      [{ id: 'node-1', type: 'classNode', position: { x: 1, y: 2 } }],
      [],
      undefined,
      undefined,
      undefined,
      {
        comment: 'Team review',
        annotations: 'Use this before migration.',
      }
    );
    const parsed = JSON.parse(result);

    expect(parsed.success).toBe(true);
    expect(mockQuery).toHaveBeenNthCalledWith(
      2,
      expect.stringContaining('INSERT INTO apiome.canvas_layouts'),
      expect.arrayContaining([
        'version-1',
        'user-1',
        'Annotated Layout',
        expect.anything(),
        expect.any(String),
        expect.any(String),
        expect.any(String),
        expect.any(String),
        expect.any(String),
        JSON.stringify({ comment: 'Team review', annotations: 'Use this before migration.' }),
      ])
    );
  });

  test('saveNamedCanvasLayout merges metadata on update and preserves unrelated keys', async () => {
    const { saveNamedCanvasLayout } = await import('../lib/db/helper');

    mockQuery
      .mockResolvedValueOnce({
        rowCount: 1,
        rows: [{ id: 'layout-4', name: 'Annotated Layout', metadata: { comment: 'Old comment', annotations: 'Existing note', extra: 'keep-me' } }],
      }) // existing layout lookup
      .mockResolvedValueOnce({ rowCount: 0 }) // BEGIN
      .mockResolvedValueOnce({
        rowCount: 1,
        rows: [{ version_id: 'version-1', user_id: 'user-1', viewport: { x: 0, y: 0, zoom: 1 }, nodes: [], edges: [], grid_settings: {}, minimap_settings: {} }],
      }) // SELECT FOR UPDATE
      .mockResolvedValueOnce({ rows: [{ n: 0 }] }) // max revision
      .mockResolvedValueOnce({ rowCount: 1 }) // insert revision
      .mockResolvedValueOnce({ rowCount: 0 }) // prune old revisions
      .mockResolvedValueOnce({ rowCount: 1, rows: [{ id: 'layout-4', name: 'Annotated Layout' }] }) // UPDATE RETURNING
      .mockResolvedValueOnce({ rowCount: 0 }); // COMMIT

    const result = await saveNamedCanvasLayout(
      'version-1',
      'user-1',
      'Annotated Layout',
      { x: 0, y: 0, zoom: 1 },
      [{ id: 'node-1', type: 'classNode', position: { x: 1, y: 2 } }],
      [],
      undefined,
      undefined,
      undefined,
      { comment: 'Updated comment' }
    );
    const parsed = JSON.parse(result);

    expect(parsed.success).toBe(true);
    expect(mockQuery).toHaveBeenNthCalledWith(
      7,
      expect.stringContaining('UPDATE apiome.canvas_layouts'),
      expect.arrayContaining([
        JSON.stringify({ comment: 'Updated comment', annotations: 'Existing note', extra: 'keep-me' }),
      ])
    );
  });

  test('saveNamedCanvasLayout clears comment on update when empty string is provided but preserves other metadata', async () => {
    const { saveNamedCanvasLayout } = await import('../lib/db/helper');

    mockQuery
      .mockResolvedValueOnce({
        rowCount: 1,
        rows: [{ id: 'layout-5', name: 'Annotated Layout', metadata: { comment: 'Old comment', annotations: 'Existing note', extra: 'keep-me' } }],
      }) // existing layout lookup
      .mockResolvedValueOnce({ rowCount: 0 }) // BEGIN
      .mockResolvedValueOnce({
        rowCount: 1,
        rows: [{ version_id: 'version-1', user_id: 'user-1', viewport: { x: 0, y: 0, zoom: 1 }, nodes: [], edges: [], grid_settings: {}, minimap_settings: {} }],
      }) // SELECT FOR UPDATE
      .mockResolvedValueOnce({ rows: [{ n: 0 }] }) // max revision
      .mockResolvedValueOnce({ rowCount: 1 }) // insert revision
      .mockResolvedValueOnce({ rowCount: 0 }) // prune old revisions
      .mockResolvedValueOnce({ rowCount: 1, rows: [{ id: 'layout-5', name: 'Annotated Layout' }] }) // UPDATE RETURNING
      .mockResolvedValueOnce({ rowCount: 0 }); // COMMIT

    const result = await saveNamedCanvasLayout(
      'version-1',
      'user-1',
      'Annotated Layout',
      { x: 0, y: 0, zoom: 1 },
      [{ id: 'node-1', type: 'classNode', position: { x: 1, y: 2 } }],
      [],
      undefined,
      undefined,
      undefined,
      { comment: '' }
    );
    const parsed = JSON.parse(result);

    expect(parsed.success).toBe(true);
    expect(mockQuery).toHaveBeenNthCalledWith(
      7,
      expect.stringContaining('UPDATE apiome.canvas_layouts'),
      expect.arrayContaining([
        JSON.stringify({ annotations: 'Existing note', extra: 'keep-me' }),
      ])
    );
  });

  test('saveNamedCanvasLayout preserves existing metadata on update when annotationsInput is omitted', async () => {
    const { saveNamedCanvasLayout } = await import('../lib/db/helper');

    mockQuery
      .mockResolvedValueOnce({
        rowCount: 1,
        rows: [{ id: 'layout-6', name: 'Annotated Layout', metadata: { comment: 'Old comment', annotations: 'Existing note', extra: 'keep-me' } }],
      }) // existing layout lookup
      .mockResolvedValueOnce({ rowCount: 0 }) // BEGIN
      .mockResolvedValueOnce({
        rowCount: 1,
        rows: [{ version_id: 'version-1', user_id: 'user-1', viewport: { x: 0, y: 0, zoom: 1 }, nodes: [], edges: [], grid_settings: {}, minimap_settings: {} }],
      }) // SELECT FOR UPDATE
      .mockResolvedValueOnce({ rows: [{ n: 0 }] }) // max revision
      .mockResolvedValueOnce({ rowCount: 1 }) // insert revision
      .mockResolvedValueOnce({ rowCount: 0 }) // prune old revisions
      .mockResolvedValueOnce({ rowCount: 1, rows: [{ id: 'layout-6', name: 'Annotated Layout' }] }) // UPDATE RETURNING
      .mockResolvedValueOnce({ rowCount: 0 }); // COMMIT

    const result = await saveNamedCanvasLayout(
      'version-1',
      'user-1',
      'Annotated Layout',
      { x: 0, y: 0, zoom: 1 },
      [{ id: 'node-1', type: 'classNode', position: { x: 1, y: 2 } }],
      [] // no annotationsInput -> should not alter existing metadata
    );
    const parsed = JSON.parse(result);

    expect(parsed.success).toBe(true);
    expect(mockQuery).toHaveBeenNthCalledWith(
      7,
      expect.stringContaining('UPDATE apiome.canvas_layouts'),
      expect.arrayContaining([
        JSON.stringify({ comment: 'Old comment', annotations: 'Existing note', extra: 'keep-me' }),
      ])
    );
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

  test('saveNamedCanvasLayout rejects invalid layout snapshot bytes', async () => {
    const { saveNamedCanvasLayout } = await import('../lib/db/helper');

    const result = await saveNamedCanvasLayout(
      'version-1',
      'user-1',
      'My Layout',
      { x: 0, y: 0, zoom: 1 },
      [{ id: 'node-1', type: 'classNode', position: { x: 1, y: 2 } }],
      [],
      undefined,
      'YQ=='
    );
    const parsed = JSON.parse(result);

    expect(parsed.success).toBe(false);
    expect(parsed.error).toBe('Layout snapshot must be a PNG image');
    expect(mockQuery).not.toHaveBeenCalled();
  });

  test('saveNamedCanvasLayout rejects oversized layout snapshot', async () => {
    const { saveNamedCanvasLayout } = await import('../lib/db/helper');

    // Construct a base64 string that exceeds the snapshot size cap when decoded (~1 MiB).
    const largeBase64 = Buffer.alloc(1024 * 1024).toString('base64');

    const result = await saveNamedCanvasLayout(
      'version-1',
      'user-1',
      'My Layout',
      { x: 0, y: 0, zoom: 1 },
      [{ id: 'node-1', type: 'classNode', position: { x: 1, y: 2 } }],
      [],
      undefined,
      largeBase64
    );
    const parsed = JSON.parse(result);

    expect(parsed.success).toBe(false);
    expect(parsed.error).toBe('Layout snapshot exceeds maximum size');
    expect(mockQuery).not.toHaveBeenCalled();
  });

  test('saveNamedCanvasLayout accepts minimal valid PNG layout snapshot', async () => {
    const { saveNamedCanvasLayout } = await import('../lib/db/helper');

    // 1x1 transparent PNG (well-known minimal valid PNG)
    const minimalPngBase64 =
      'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9VZwAAAABJRU5ErkJggg==';

    mockQuery
      .mockResolvedValueOnce({ rowCount: 0, rows: [] }) // existing layout lookup
      .mockResolvedValueOnce({ rowCount: 1, rows: [{ id: 'layout-with-snapshot-1', name: 'My Layout' }] }); // INSERT RETURNING

    const result = await saveNamedCanvasLayout(
      'version-1',
      'user-1',
      'My Layout',
      { x: 0, y: 0, zoom: 1 },
      [{ id: 'node-1', type: 'classNode', position: { x: 1, y: 2 } }],
      [],
      undefined,
      minimalPngBase64
    );
    const parsed = JSON.parse(result);

    expect(parsed.success).toBe(true);
    expect(parsed.layout.id).toBe('layout-with-snapshot-1');

    // Ensure the INSERT query was called and included a snapshot image argument.
    expect(mockQuery).toHaveBeenCalledWith(
      expect.stringContaining('INSERT INTO apiome.canvas_layouts'),
      expect.arrayContaining([
        'version-1',
        'user-1',
        'My Layout',
        expect.any(Buffer), // snapshot_image
      ])
    );
  });

  test('saveNamedCanvasLayout creates shared layout when userId is null and trims name', async () => {
    const { saveNamedCanvasLayout } = await import('../lib/db/helper');

    mockQuery
      .mockResolvedValueOnce({ rowCount: 1, rows: [{ '?column?': 1 }] }) // version belongs to tenant
      .mockResolvedValueOnce({ rowCount: 1, rows: [{ '?column?': 1 }] }) // user is tenant admin
      .mockResolvedValueOnce({ rowCount: 0, rows: [] }) // existing lookup
      .mockResolvedValueOnce({ rowCount: 1, rows: [{ id: 'layout-shared-1', name: 'Shared Layout' }] }); // create return

    const result = await saveNamedCanvasLayout(
      'version-1',
      null,
      '  Shared Layout  ',
      { x: 0, y: 0, zoom: 1 },
      [{ id: 'node-1', type: 'classNode', position: { x: 1, y: 2 } }],
      [],
      undefined,
      undefined,
      'tenant-1'
    );
    const parsed = JSON.parse(result);

    expect(parsed.success).toBe(true);
    expect(parsed.layout.id).toBe('layout-shared-1');

    expect(mockQuery).toHaveBeenNthCalledWith(
      3,
      expect.stringContaining('user_id IS NOT DISTINCT FROM $3'),
      ['version-1', 'Shared Layout', null]
    );
    expect(mockQuery).toHaveBeenNthCalledWith(
      4,
      expect.stringContaining('INSERT INTO apiome.canvas_layouts'),
      expect.arrayContaining(['version-1', null, 'Shared Layout'])
    );
  });

  test('saveNamedCanvasLayout updates existing shared layout when userId is null', async () => {
    const { saveNamedCanvasLayout } = await import('../lib/db/helper');

    mockQuery
      .mockResolvedValueOnce({ rowCount: 1, rows: [{ '?column?': 1 }] }) // version belongs to tenant
      .mockResolvedValueOnce({ rowCount: 1, rows: [{ '?column?': 1 }] }) // user is tenant admin
      .mockResolvedValueOnce({ rowCount: 1, rows: [{ id: 'layout-shared-1' }] }) // existing lookup (pool)
      .mockResolvedValueOnce({ rowCount: 0 }) // BEGIN
      .mockResolvedValueOnce({
        rowCount: 1,
        rows: [
          {
            version_id: 'version-1',
            user_id: null,
            viewport: { x: 0, y: 0, zoom: 1 },
            nodes: [],
            edges: [],
            grid_settings: {},
            minimap_settings: {}
          }
        ]
      }) // SELECT FOR UPDATE
      .mockResolvedValueOnce({ rows: [{ n: 2 }] }) // max revision
      .mockResolvedValueOnce({ rowCount: 1 }) // insert revision
      .mockResolvedValueOnce({ rowCount: 0 }) // prune
      .mockResolvedValueOnce({ rowCount: 1, rows: [{ id: 'layout-shared-1', name: 'Shared Layout' }] }) // UPDATE RETURNING
      .mockResolvedValueOnce({ rowCount: 0 }); // COMMIT

    const result = await saveNamedCanvasLayout(
      'version-1',
      null,
      'Shared Layout',
      { x: 0, y: 0, zoom: 1 },
      [{ id: 'node-1', type: 'classNode', position: { x: 1, y: 2 } }],
      [],
      undefined,
      undefined,
      'tenant-1'
    );
    const parsed = JSON.parse(result);

    expect(parsed.success).toBe(true);
    expect(parsed.layout.id).toBe('layout-shared-1');
    expect(mockQuery).toHaveBeenNthCalledWith(
      3,
      expect.stringContaining('user_id IS NOT DISTINCT FROM $3'),
      ['version-1', 'Shared Layout', null]
    );
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

  test('setTenantCanvasLayoutDefaultName rejects when user is not tenant admin', async () => {
    const { setTenantCanvasLayoutDefaultName } = await import('../lib/db/helper');

    mockQuery.mockResolvedValueOnce({ rowCount: 0, rows: [] });

    const result = await setTenantCanvasLayoutDefaultName(
      'version-1',
      'tenant-1',
      'Presentation Layout'
    );
    const parsed = JSON.parse(result);

    expect(parsed.success).toBe(false);
    expect(parsed.error).toContain('administrators');
  });

  test('setTenantCanvasLayoutDefaultName inserts when admin and version belongs to tenant', async () => {
    const { setTenantCanvasLayoutDefaultName } = await import('../lib/db/helper');

    mockQuery
      .mockResolvedValueOnce({ rowCount: 1, rows: [{ '?column?': 1 }] })
      .mockResolvedValueOnce({ rowCount: 1, rows: [{ '?column?': 1 }] })
      .mockResolvedValueOnce({ rowCount: 1, rows: [] });

    const result = await setTenantCanvasLayoutDefaultName(
      'version-1',
      'tenant-1',
      'Dependency Layout'
    );
    const parsed = JSON.parse(result);

    expect(parsed.success).toBe(true);
    expect(mockQuery).toHaveBeenCalledTimes(3);
  });

  test('setUserCanvasLayoutDefaultName rejects when unauthenticated', async () => {
    mockGetAuthSession.mockResolvedValueOnce(null);

    const { setUserCanvasLayoutDefaultName } = await import('../lib/db/helper');

    const result = await setUserCanvasLayoutDefaultName('version-1', 'Presentation Layout');
    const parsed = JSON.parse(result);

    expect(parsed.success).toBe(false);
    expect(parsed.error).toBe('Unauthorized');
    expect(mockQuery).not.toHaveBeenCalled();
  });

  test('setUserCanvasLayoutDefaultName saves default for authenticated user', async () => {
    const { setUserCanvasLayoutDefaultName } = await import('../lib/db/helper');

    mockQuery.mockResolvedValueOnce({ rowCount: 1 });

    const result = await setUserCanvasLayoutDefaultName('version-1', 'My Layout');
    const parsed = JSON.parse(result);

    expect(parsed.success).toBe(true);
    expect(parsed.layoutName).toBe('My Layout');
    expect(mockQuery).toHaveBeenCalledWith(
      expect.stringContaining('user_canvas_layout_defaults'),
      ['user-1', 'version-1', 'My Layout']
    );
  });

  test('clearUserCanvasLayoutDefaultName rejects when unauthenticated', async () => {
    mockGetAuthSession.mockResolvedValueOnce(null);

    const { clearUserCanvasLayoutDefaultName } = await import('../lib/db/helper');

    const result = await clearUserCanvasLayoutDefaultName('version-1');
    const parsed = JSON.parse(result);

    expect(parsed.success).toBe(false);
    expect(parsed.error).toBe('Unauthorized');
    expect(mockQuery).not.toHaveBeenCalled();
  });

  test('setTenantCanvasLayoutDefaultName rejects when unauthenticated', async () => {
    mockGetAuthSession.mockResolvedValueOnce(null);

    const { setTenantCanvasLayoutDefaultName } = await import('../lib/db/helper');

    const result = await setTenantCanvasLayoutDefaultName('version-1', 'tenant-1', 'Some Layout');
    const parsed = JSON.parse(result);

    expect(parsed.success).toBe(false);
    expect(parsed.error).toBe('Unauthorized');
    expect(mockQuery).not.toHaveBeenCalled();
  });

  test('clearTenantCanvasLayoutDefaultName rejects when unauthenticated', async () => {
    mockGetAuthSession.mockResolvedValueOnce(null);

    const { clearTenantCanvasLayoutDefaultName } = await import('../lib/db/helper');

    const result = await clearTenantCanvasLayoutDefaultName('version-1', 'tenant-1');
    const parsed = JSON.parse(result);

    expect(parsed.success).toBe(false);
    expect(parsed.error).toBe('Unauthorized');
    expect(mockQuery).not.toHaveBeenCalled();
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

  test('deleteNamedCanvasLayout deletes personal layout owned by current user', async () => {
    const { deleteNamedCanvasLayout } = await import('../lib/db/helper');

    mockQuery
      .mockResolvedValueOnce({
        rowCount: 1,
        rows: [{ id: 'layout-1', user_id: 'user-1', name: 'My Layout' }],
      })
      .mockResolvedValueOnce({ rowCount: 1, rows: [{ id: 'layout-1' }] });

    const result = await deleteNamedCanvasLayout('version-1', 'My Layout', 'tenant-1');
    const parsed = JSON.parse(result);

    expect(parsed.success).toBe(true);
    expect(parsed.deleted).toBe(true);
    expect(mockQuery).toHaveBeenNthCalledWith(
      1,
      expect.stringContaining('FROM apiome.canvas_layouts'),
      ['version-1', 'My Layout', 'user-1']
    );
    expect(mockQuery).toHaveBeenNthCalledWith(
      2,
      expect.stringContaining('DELETE FROM apiome.canvas_layouts'),
      ['layout-1']
    );
  });

  test('deleteNamedCanvasLayout rejects shared delete for non-admin', async () => {
    const { deleteNamedCanvasLayout } = await import('../lib/db/helper');

    mockQuery
      .mockResolvedValueOnce({
        rowCount: 1,
        rows: [{ id: 'layout-shared-1', user_id: null, name: 'Shared Layout' }],
      })
      .mockResolvedValueOnce({ rowCount: 1, rows: [{ '?column?': 1 }] }) // version belongs to tenant
      .mockResolvedValueOnce({ rowCount: 0, rows: [] }); // not admin

    const result = await deleteNamedCanvasLayout('version-1', 'Shared Layout', 'tenant-1');
    const parsed = JSON.parse(result);

    expect(parsed.success).toBe(false);
    expect(parsed.error).toContain('tenant administrators');
  });

  test('deleteNamedCanvasLayout deletes shared layout when called by tenant admin', async () => {
    const { deleteNamedCanvasLayout } = await import('../lib/db/helper');

    mockQuery
      .mockResolvedValueOnce({
        rowCount: 1,
        rows: [{ id: 'layout-shared-1', user_id: null, name: 'Shared Layout' }],
      }) // shared layout
      .mockResolvedValueOnce({ rowCount: 1, rows: [{ '?column?': 1 }] }) // version belongs to tenant
      .mockResolvedValueOnce({ rowCount: 1, rows: [{ '?column?': 1 }] }) // user is tenant admin
      .mockResolvedValueOnce({ rowCount: 1, rows: [{ id: 'layout-shared-1' }] }); // delete

    const result = await deleteNamedCanvasLayout('version-1', 'Shared Layout', 'tenant-1');
    const parsed = JSON.parse(result);

    expect(parsed.success).toBe(true);
    expect(parsed.deleted).toBe(true);
    expect(mockQuery).toHaveBeenCalledTimes(4);
  });

  test('deleteNamedCanvasLayout errors when deleting shared layout without tenantId', async () => {
    const { deleteNamedCanvasLayout } = await import('../lib/db/helper');

    mockQuery.mockResolvedValueOnce({
      rowCount: 1,
      rows: [{ id: 'layout-shared-1', user_id: null, name: 'Shared Layout' }],
    });

    const result = await deleteNamedCanvasLayout('version-1', 'Shared Layout', undefined as any);
    const parsed = JSON.parse(result);

    expect(parsed.success).toBe(false);
    expect(parsed.error).toBeDefined();
    expect(mockQuery).toHaveBeenCalledTimes(1);
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
