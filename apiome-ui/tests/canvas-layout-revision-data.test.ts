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

describe('Database Helper - getCanvasLayoutRevisionData', () => {
  let mockQuery: jest.Mock<any>;
  let mockGetAuthSession: jest.Mock<any>;

  beforeEach(() => {
    const db = require('../lib/db/db');
    mockQuery = db.query as jest.Mock;
    mockQuery.mockReset();

    const serverSession = require('../lib/auth/server-session');
    mockGetAuthSession = serverSession.getAuthSession as jest.Mock<any>;
    mockGetAuthSession.mockResolvedValue({
      user: { user_id: 'session-user-1' },
    });
  });

  test('returns full revision data with viewport, nodes, edges, and settings', async () => {
    const { getCanvasLayoutRevisionData } = await import('../lib/db/helper');

    const revisionData = {
      id: 'rev-1',
      revision: 3,
      viewport: { x: 100, y: 200, zoom: 0.5 },
      nodes: [
        { id: 'n1', type: 'classNode', position: { x: 10, y: 20 } },
        { id: 'n2', type: 'classNode', position: { x: 30, y: 40 } },
      ],
      edges: [{ id: 'e1', source: 'n1', target: 'n2' }],
      grid_settings: { size: 20, snapToGrid: true },
      minimap_settings: { visible: true },
      created_at: '2026-03-30T10:00:00Z',
      created_by: 'user-1',
    };

    mockQuery.mockResolvedValue({ rowCount: 1, rows: [revisionData] });

    const result = await getCanvasLayoutRevisionData('rev-1', 'layout-1', 'version-1');
    const parsed = JSON.parse(result);

    expect(parsed.success).toBe(true);
    expect(parsed.revision.id).toBe('rev-1');
    expect(parsed.revision.viewport).toEqual({ x: 100, y: 200, zoom: 0.5 });
    expect(parsed.revision.nodes).toHaveLength(2);
    expect(parsed.revision.edges).toHaveLength(1);
    expect(parsed.revision.grid_settings).toEqual({ size: 20, snapToGrid: true });
  });

  test('returns error when revision is not found', async () => {
    const { getCanvasLayoutRevisionData } = await import('../lib/db/helper');

    mockQuery.mockResolvedValue({ rowCount: 0, rows: [] });

    const result = await getCanvasLayoutRevisionData('nonexistent', 'layout-1', 'version-1');
    const parsed = JSON.parse(result);

    expect(parsed.success).toBe(false);
    expect(parsed.error).toBe('Revision not found');
  });

  test('queries with correct parameters derived from session (access control)', async () => {
    const { getCanvasLayoutRevisionData } = await import('../lib/db/helper');

    mockQuery.mockResolvedValue({
      rowCount: 1,
      rows: [{ id: 'rev-1', revision: 1, viewport: null, nodes: [], edges: [] }],
    });

    await getCanvasLayoutRevisionData('rev-id', 'layout-id', 'ver-id');

    expect(mockQuery).toHaveBeenCalledWith(
      expect.stringContaining('canvas_layout_revisions'),
      ['rev-id', 'layout-id', 'ver-id', 'session-user-1']
    );
    expect(mockQuery).toHaveBeenCalledWith(
      expect.stringContaining('cl.user_id = $4 OR cl.user_id IS NULL'),
      expect.any(Array)
    );
  });

  test('returns Unauthorized when no session', async () => {
    mockGetAuthSession.mockResolvedValue(null);

    const { getCanvasLayoutRevisionData } = await import('../lib/db/helper');

    const result = await getCanvasLayoutRevisionData('rev-1', 'layout-1', 'version-1');
    const parsed = JSON.parse(result);

    expect(parsed.success).toBe(false);
    expect(parsed.error).toBe('Unauthorized');
    expect(mockQuery).not.toHaveBeenCalled();
  });

  test('handles database errors gracefully', async () => {
    const { getCanvasLayoutRevisionData } = await import('../lib/db/helper');

    mockQuery.mockRejectedValue(new Error('Connection failed'));

    const result = await getCanvasLayoutRevisionData('rev-1', 'layout-1', 'version-1');
    const parsed = JSON.parse(result);

    expect(parsed.success).toBe(false);
    expect(parsed.error).toBe('Connection failed');
  });
});
