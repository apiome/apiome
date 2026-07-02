import { beforeEach, describe, expect, jest, test } from '@jest/globals';

jest.mock('../lib/db/helper', () => ({
  getDefaultCanvasLayout: jest.fn(),
  getEffectiveDefaultLayoutName: jest.fn(),
  getNamedCanvasLayout: jest.fn(),
}));

import { getDefaultCanvasLayout, getEffectiveDefaultLayoutName, getNamedCanvasLayout } from '../lib/db/helper';
import { rowToLayoutState, loadLayoutStateForVersionCompare } from '../lib/version-canvas-layout';

const mockGetDefault = getDefaultCanvasLayout as jest.Mock<any>;
const mockGetEffective = getEffectiveDefaultLayoutName as jest.Mock<any>;
const mockGetNamed = getNamedCanvasLayout as jest.Mock<any>;

describe('rowToLayoutState', () => {
  test('parses string JSON columns into LayoutState', () => {
    const row = {
      viewport: '{"x":1,"y":2,"zoom":0.5}',
      nodes: '[{"id":"a","position":{"x":0,"y":0},"data":{"name":"N"}}]',
      edges: '[{"id":"e1","source":"a","target":"b"}]',
      grid_settings: '{"snapToGrid":true}',
      minimap_settings: '{}',
    };
    const s = rowToLayoutState(row);
    expect(s.viewport).toEqual({ x: 1, y: 2, zoom: 0.5 });
    expect(s.nodes).toHaveLength(1);
    expect(s.nodes![0].id).toBe('a');
    expect(s.edges).toHaveLength(1);
    expect(s.grid_settings).toEqual({ snapToGrid: true });
  });

  test('accepts already-parsed objects', () => {
    const row = {
      viewport: { x: 0, y: 0, zoom: 1 },
      nodes: [{ id: 'x', position: { x: 10, y: 20 } }],
      edges: [],
    };
    const s = rowToLayoutState(row);
    expect(s.nodes).toHaveLength(1);
    expect(s.edges).toEqual([]);
  });
});

describe('loadLayoutStateForVersionCompare', () => {
  const sampleRow = {
    nodes: '[{"id":"n1","position":{"x":0,"y":0},"data":{"name":"Node1"}}]',
    edges: '[]',
  };

  beforeEach(() => {
    mockGetDefault.mockReset();
    mockGetEffective.mockReset();
    mockGetNamed.mockReset();
  });

  test('returns layout from default row when it exists', async () => {
    mockGetDefault.mockResolvedValue(JSON.stringify({ success: true, layout: sampleRow }));

    const result = await loadLayoutStateForVersionCompare('v1', undefined, undefined);

    expect(mockGetDefault).toHaveBeenCalledWith('v1', undefined);
    expect(mockGetEffective).not.toHaveBeenCalled();
    expect(result).not.toBeNull();
    expect(result!.nodes).toHaveLength(1);
    expect(result!.nodes![0].id).toBe('n1');
  });

  test('falls back to effective named layout when default row is absent', async () => {
    mockGetDefault.mockResolvedValue(JSON.stringify({ success: true, layout: null }));
    mockGetEffective.mockResolvedValue(JSON.stringify({ success: true, layoutName: 'My Layout' }));
    mockGetNamed.mockResolvedValue(JSON.stringify({ success: true, layout: sampleRow }));

    const result = await loadLayoutStateForVersionCompare('v1', undefined, undefined);

    expect(mockGetEffective).toHaveBeenCalledWith('v1', undefined, undefined);
    expect(mockGetNamed).toHaveBeenCalledWith('v1', null, 'My Layout');
    expect(result).not.toBeNull();
    expect(result!.nodes).toHaveLength(1);
  });

  test('returns null when default row absent and named layout fetch fails', async () => {
    mockGetDefault.mockResolvedValue(JSON.stringify({ success: true, layout: null }));
    mockGetEffective.mockResolvedValue(JSON.stringify({ success: true, layoutName: 'Dev Layout' }));
    mockGetNamed.mockResolvedValue(JSON.stringify({ success: false }));

    const result = await loadLayoutStateForVersionCompare('v1', undefined, undefined);

    expect(result).toBeNull();
  });

  test('returns null when default fails and effective layout name not resolved', async () => {
    mockGetDefault.mockResolvedValue(JSON.stringify({ success: false }));
    mockGetEffective.mockResolvedValue(JSON.stringify({ success: false }));

    const result = await loadLayoutStateForVersionCompare('v1', undefined, undefined);

    expect(result).toBeNull();
  });

  test('does not forward caller-supplied userId/tenantId to server actions', async () => {
    mockGetDefault.mockResolvedValue(JSON.stringify({ success: true, layout: sampleRow }));

    await loadLayoutStateForVersionCompare('v1', 'user-abc', 'tenant-xyz');

    // Must always be called with undefined, never with the caller-supplied values
    expect(mockGetDefault).toHaveBeenCalledWith('v1', undefined);
    expect(mockGetEffective).not.toHaveBeenCalled();
  });

  test('returns null when effective layoutName is empty string', async () => {
    mockGetDefault.mockResolvedValue(JSON.stringify({ success: true, layout: null }));
    mockGetEffective.mockResolvedValue(JSON.stringify({ success: true, layoutName: '' }));

    const result = await loadLayoutStateForVersionCompare('v1', undefined, undefined);

    expect(mockGetNamed).not.toHaveBeenCalled();
    expect(result).toBeNull();
  });
});
