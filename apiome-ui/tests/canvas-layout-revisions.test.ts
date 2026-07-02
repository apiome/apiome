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

describe('Database Helper - Canvas layout revisions', () => {
  let mockQuery: jest.Mock<any>;

  beforeEach(() => {
    const db = require('../lib/db/db');
    mockQuery = db.query as jest.Mock;
    mockQuery.mockReset();
  });

  test('listCanvasLayoutRevisions returns revisions ordered newest first', async () => {
    const { listCanvasLayoutRevisions } = await import('../lib/db/helper');

    mockQuery.mockResolvedValue({
      rows: [
        { id: 'r2', canvas_layout_id: 'layout-1', revision: 2, created_at: '2026-01-01T00:00:00Z', created_by: 'u1' },
        { id: 'r1', canvas_layout_id: 'layout-1', revision: 1, created_at: '2025-12-01T00:00:00Z', created_by: 'u1' },
      ],
    });

    const result = await listCanvasLayoutRevisions('layout-1', 'version-1', 'user-1', 50);
    const parsed = JSON.parse(result);

    expect(parsed.success).toBe(true);
    expect(parsed.revisions).toHaveLength(2);
    expect(mockQuery).toHaveBeenCalledWith(
      expect.stringContaining('ORDER BY r.revision DESC'),
      ['layout-1', 'version-1', 'user-1', 50]
    );
  });

  test('restoreCanvasLayoutFromRevision applies snapshot and records prior state', async () => {
    const { restoreCanvasLayoutFromRevision } = await import('../lib/db/helper');

    const priorSnapshot = {
      viewport: { x: 0, y: 0, zoom: 1 },
      nodes: [{ id: 'n1' }],
      edges: [],
      grid_settings: {},
      minimap_settings: {},
    };

    mockQuery
      .mockResolvedValueOnce({
        rowCount: 1,
        rows: [priorSnapshot],
      }) // revision row (pool)
      .mockResolvedValueOnce({ rowCount: 0 }) // BEGIN
      .mockResolvedValueOnce({
        rowCount: 1,
        rows: [
          {
            version_id: 'version-1',
            user_id: 'user-1',
            viewport: { x: 10, y: 10, zoom: 0.5 },
            nodes: [{ id: 'n2' }],
            edges: [],
            grid_settings: {},
            minimap_settings: {},
          },
        ],
      }) // SELECT FOR UPDATE
      .mockResolvedValueOnce({ rows: [{ n: 3 }] })
      .mockResolvedValueOnce({ rowCount: 1 })
      .mockResolvedValueOnce({ rowCount: 0 })
      .mockResolvedValueOnce({
        rowCount: 1,
        rows: [{ id: 'layout-1', viewport: priorSnapshot.viewport, nodes: priorSnapshot.nodes }],
      })
      .mockResolvedValueOnce({ rowCount: 0 }); // COMMIT

    const result = await restoreCanvasLayoutFromRevision('layout-1', 'rev-uuid', 'version-1', 'user-1');
    const parsed = JSON.parse(result);

    expect(parsed.success).toBe(true);
    expect(mockQuery).toHaveBeenNthCalledWith(
      1,
      expect.stringContaining('FROM apiome.canvas_layout_revisions r'),
      ['rev-uuid', 'layout-1', 'version-1', 'user-1']
    );
  });
});
