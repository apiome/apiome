import { describe, expect, test } from '@jest/globals';
import {
  compareLayouts,
  flattenDiffEntries,
  type LayoutState,
} from '../lib/layout-diff';

describe('layout-diff', () => {
  const emptyState: LayoutState = {
    viewport: { x: 0, y: 0, zoom: 1 },
    nodes: [],
    edges: [],
    grid_settings: null,
    minimap_settings: null,
  };

  describe('compareLayouts — nodes', () => {
    test('detects added nodes', () => {
      const left: LayoutState = { ...emptyState, nodes: [] };
      const right: LayoutState = {
        ...emptyState,
        nodes: [{ id: 'n1', type: 'classNode', position: { x: 10, y: 20 } }],
      };
      const diff = compareLayouts(left, right);

      expect(diff.nodes.added).toHaveLength(1);
      expect(diff.nodes.added[0].id).toBe('n1');
      expect(diff.nodes.added[0].type).toBe('added');
      expect(diff.nodes.removed).toHaveLength(0);
      expect(diff.nodes.modified).toHaveLength(0);
    });

    test('detects removed nodes', () => {
      const left: LayoutState = {
        ...emptyState,
        nodes: [{ id: 'n1', type: 'classNode', position: { x: 10, y: 20 } }],
      };
      const right: LayoutState = { ...emptyState, nodes: [] };
      const diff = compareLayouts(left, right);

      expect(diff.nodes.removed).toHaveLength(1);
      expect(diff.nodes.removed[0].id).toBe('n1');
      expect(diff.nodes.added).toHaveLength(0);
    });

    test('detects position changes', () => {
      const left: LayoutState = {
        ...emptyState,
        nodes: [{ id: 'n1', type: 'classNode', position: { x: 10, y: 20 } }],
      };
      const right: LayoutState = {
        ...emptyState,
        nodes: [{ id: 'n1', type: 'classNode', position: { x: 100, y: 200 } }],
      };
      const diff = compareLayouts(left, right);

      expect(diff.nodes.modified).toHaveLength(1);
      expect(diff.nodes.modified[0].changes).toContain('position');
    });

    test('detects dimension changes', () => {
      const left: LayoutState = {
        ...emptyState,
        nodes: [
          {
            id: 'n1',
            type: 'classNode',
            position: { x: 0, y: 0 },
            dimensions: { width: 100, height: 50 },
          },
        ],
      };
      const right: LayoutState = {
        ...emptyState,
        nodes: [
          {
            id: 'n1',
            type: 'classNode',
            position: { x: 0, y: 0 },
            dimensions: { width: 200, height: 50 },
          },
        ],
      };
      const diff = compareLayouts(left, right);

      expect(diff.nodes.modified).toHaveLength(1);
      expect(diff.nodes.modified[0].changes).toContain('dimensions');
      expect(diff.nodes.modified[0].changes).not.toContain('position');
    });

    test('detects type changes', () => {
      const left: LayoutState = {
        ...emptyState,
        nodes: [{ id: 'n1', type: 'classNode', position: { x: 0, y: 0 } }],
      };
      const right: LayoutState = {
        ...emptyState,
        nodes: [{ id: 'n1', type: 'groupNode', position: { x: 0, y: 0 } }],
      };
      const diff = compareLayouts(left, right);

      expect(diff.nodes.modified).toHaveLength(1);
      expect(diff.nodes.modified[0].changes).toContain('type');
    });

    test('detects data changes on group nodes', () => {
      const left: LayoutState = {
        ...emptyState,
        nodes: [
          {
            id: 'g1',
            type: 'groupNode',
            position: { x: 0, y: 0 },
            data: { name: 'Group A', color: 'blue', nodeIds: ['n1'] },
          },
        ],
      };
      const right: LayoutState = {
        ...emptyState,
        nodes: [
          {
            id: 'g1',
            type: 'groupNode',
            position: { x: 0, y: 0 },
            data: { name: 'Group B', color: 'red', nodeIds: ['n1', 'n2'] },
          },
        ],
      };
      const diff = compareLayouts(left, right);

      expect(diff.nodes.modified).toHaveLength(1);
      expect(diff.nodes.modified[0].changes).toContain('data');
    });

    test('detects data added when left has no data but right does', () => {
      const left: LayoutState = {
        ...emptyState,
        nodes: [{ id: 'n1', type: 'classNode', position: { x: 0, y: 0 } }],
      };
      const right: LayoutState = {
        ...emptyState,
        nodes: [{ id: 'n1', type: 'classNode', position: { x: 0, y: 0 }, data: { label: 'new' } }],
      };
      const diff = compareLayouts(left, right);

      expect(diff.nodes.modified).toHaveLength(1);
      expect(diff.nodes.modified[0].changes).toContain('data');
    });

    test('detects data removed when left has data but right does not', () => {
      const left: LayoutState = {
        ...emptyState,
        nodes: [{ id: 'n1', type: 'classNode', position: { x: 0, y: 0 }, data: { label: 'old' } }],
      };
      const right: LayoutState = {
        ...emptyState,
        nodes: [{ id: 'n1', type: 'classNode', position: { x: 0, y: 0 } }],
      };
      const diff = compareLayouts(left, right);

      expect(diff.nodes.modified).toHaveLength(1);
      expect(diff.nodes.modified[0].changes).toContain('data');
    });

    test('reports unchanged node count', () => {
      const nodes = [
        { id: 'n1', type: 'classNode', position: { x: 10, y: 20 } },
        { id: 'n2', type: 'classNode', position: { x: 30, y: 40 } },
      ];
      const diff = compareLayouts(
        { ...emptyState, nodes },
        { ...emptyState, nodes }
      );

      expect(diff.nodes.unchanged).toBe(2);
      expect(diff.nodes.added).toHaveLength(0);
      expect(diff.nodes.removed).toHaveLength(0);
      expect(diff.nodes.modified).toHaveLength(0);
    });

    test('ignores sub-threshold position changes', () => {
      const left: LayoutState = {
        ...emptyState,
        nodes: [{ id: 'n1', type: 'classNode', position: { x: 10, y: 20 } }],
      };
      const right: LayoutState = {
        ...emptyState,
        nodes: [{ id: 'n1', type: 'classNode', position: { x: 10.3, y: 20.1 } }],
      };
      const diff = compareLayouts(left, right);

      expect(diff.nodes.modified).toHaveLength(0);
      expect(diff.nodes.unchanged).toBe(1);
    });

    test('uses node data name as label for group nodes', () => {
      const left: LayoutState = { ...emptyState, nodes: [] };
      const right: LayoutState = {
        ...emptyState,
        nodes: [
          {
            id: 'g1',
            type: 'groupNode',
            position: { x: 0, y: 0 },
            data: { name: 'My Group' },
          },
        ],
      };
      const diff = compareLayouts(left, right);

      expect(diff.nodes.added[0].label).toBe('My Group');
    });
  });

  describe('compareLayouts — edges', () => {
    test('detects added edges', () => {
      const left: LayoutState = { ...emptyState, edges: [] };
      const right: LayoutState = {
        ...emptyState,
        edges: [{ id: 'e1', source: 'a', target: 'b' }],
      };
      const diff = compareLayouts(left, right);

      expect(diff.edges.added).toHaveLength(1);
      expect(diff.edges.added[0].label).toBe('a → b');
    });

    test('detects removed edges', () => {
      const left: LayoutState = {
        ...emptyState,
        edges: [{ id: 'e1', source: 'a', target: 'b' }],
      };
      const right: LayoutState = { ...emptyState, edges: [] };
      const diff = compareLayouts(left, right);

      expect(diff.edges.removed).toHaveLength(1);
    });

    test('detects reconnected edges (source change)', () => {
      const left: LayoutState = {
        ...emptyState,
        edges: [{ id: 'e1', source: 'a', target: 'b' }],
      };
      const right: LayoutState = {
        ...emptyState,
        edges: [{ id: 'e1', source: 'c', target: 'b' }],
      };
      const diff = compareLayouts(left, right);

      expect(diff.edges.modified).toHaveLength(1);
      expect(diff.edges.modified[0].changes).toContain('source');
    });

    test('detects handle changes', () => {
      const left: LayoutState = {
        ...emptyState,
        edges: [{ id: 'e1', source: 'a', target: 'b', sourceHandle: 'h1', targetHandle: 'h2' }],
      };
      const right: LayoutState = {
        ...emptyState,
        edges: [{ id: 'e1', source: 'a', target: 'b', sourceHandle: 'h3', targetHandle: 'h2' }],
      };
      const diff = compareLayouts(left, right);

      expect(diff.edges.modified).toHaveLength(1);
      expect(diff.edges.modified[0].changes).toContain('sourceHandle');
      expect(diff.edges.modified[0].changes).not.toContain('targetHandle');
    });

    test('reports unchanged edge count', () => {
      const edges = [{ id: 'e1', source: 'a', target: 'b' }];
      const diff = compareLayouts(
        { ...emptyState, edges },
        { ...emptyState, edges }
      );

      expect(diff.edges.unchanged).toBe(1);
    });
  });

  describe('compareLayouts — viewport', () => {
    test('detects viewport pan changes', () => {
      const left: LayoutState = { ...emptyState, viewport: { x: 0, y: 0, zoom: 1 } };
      const right: LayoutState = { ...emptyState, viewport: { x: 100, y: 200, zoom: 1 } };
      const diff = compareLayouts(left, right);

      expect(diff.viewport).not.toBeNull();
      expect(diff.viewport!.changes).toContain('x');
      expect(diff.viewport!.changes).toContain('y');
    });

    test('detects viewport zoom changes', () => {
      const left: LayoutState = { ...emptyState, viewport: { x: 0, y: 0, zoom: 1 } };
      const right: LayoutState = { ...emptyState, viewport: { x: 0, y: 0, zoom: 0.5 } };
      const diff = compareLayouts(left, right);

      expect(diff.viewport).not.toBeNull();
      expect(diff.viewport!.changes).toContain('zoom');
    });

    test('returns null for identical viewports', () => {
      const diff = compareLayouts(
        { ...emptyState, viewport: { x: 5, y: 10, zoom: 1.5 } },
        { ...emptyState, viewport: { x: 5, y: 10, zoom: 1.5 } }
      );

      expect(diff.viewport).toBeNull();
    });

    test('handles null viewports gracefully', () => {
      const diff = compareLayouts(
        { ...emptyState, viewport: null },
        { ...emptyState, viewport: null }
      );

      expect(diff.viewport).toBeNull();
    });
  });

  describe('compareLayouts — settings', () => {
    test('detects grid setting changes', () => {
      const left: LayoutState = {
        ...emptyState,
        grid_settings: { size: 20, snapToGrid: true, showGrid: true },
      };
      const right: LayoutState = {
        ...emptyState,
        grid_settings: { size: 40, snapToGrid: false, showGrid: true },
      };
      const diff = compareLayouts(left, right);

      expect(diff.gridSettings).not.toBeNull();
      expect(diff.gridSettings!.changes).toContain('size');
      expect(diff.gridSettings!.changes).toContain('snapToGrid');
      expect(diff.gridSettings!.changes).not.toContain('showGrid');
    });

    test('detects minimap setting changes', () => {
      const left: LayoutState = { ...emptyState, minimap_settings: { visible: true } };
      const right: LayoutState = { ...emptyState, minimap_settings: { visible: false } };
      const diff = compareLayouts(left, right);

      expect(diff.minimapSettings).not.toBeNull();
    });

    test('returns null for identical settings', () => {
      const settings = { size: 20, snapToGrid: true };
      const diff = compareLayouts(
        { ...emptyState, grid_settings: settings },
        { ...emptyState, grid_settings: settings }
      );

      expect(diff.gridSettings).toBeNull();
    });

    test('handles null settings gracefully', () => {
      const diff = compareLayouts(
        { ...emptyState, grid_settings: null, minimap_settings: null },
        { ...emptyState, grid_settings: null, minimap_settings: null }
      );

      expect(diff.gridSettings).toBeNull();
      expect(diff.minimapSettings).toBeNull();
    });
  });

  describe('compareLayouts — totalChanges', () => {
    test('counts all change types', () => {
      const left: LayoutState = {
        viewport: { x: 0, y: 0, zoom: 1 },
        nodes: [
          { id: 'n1', type: 'classNode', position: { x: 0, y: 0 } },
          { id: 'n2', type: 'classNode', position: { x: 10, y: 10 } },
        ],
        edges: [{ id: 'e1', source: 'n1', target: 'n2' }],
        grid_settings: { size: 20 },
        minimap_settings: null,
      };
      const right: LayoutState = {
        viewport: { x: 500, y: 500, zoom: 2 },
        nodes: [
          { id: 'n1', type: 'classNode', position: { x: 100, y: 200 } },
          { id: 'n3', type: 'classNode', position: { x: 50, y: 50 } },
        ],
        edges: [{ id: 'e2', source: 'n1', target: 'n3' }],
        grid_settings: { size: 40 },
        minimap_settings: null,
      };
      const diff = compareLayouts(left, right);

      expect(diff.nodes.added).toHaveLength(1);
      expect(diff.nodes.removed).toHaveLength(1);
      expect(diff.nodes.modified).toHaveLength(1);
      expect(diff.edges.added).toHaveLength(1);
      expect(diff.edges.removed).toHaveLength(1);
      expect(diff.viewport).not.toBeNull();
      expect(diff.gridSettings).not.toBeNull();
      expect(diff.totalChanges).toBe(7);
    });

    test('is zero for identical layouts', () => {
      const state: LayoutState = {
        viewport: { x: 5, y: 10, zoom: 1 },
        nodes: [{ id: 'n1', position: { x: 0, y: 0 } }],
        edges: [{ id: 'e1', source: 'n1', target: 'n1' }],
        grid_settings: { size: 20 },
        minimap_settings: { visible: true },
      };
      const diff = compareLayouts(state, state);

      expect(diff.totalChanges).toBe(0);
    });
  });

  describe('compareLayouts — null/undefined safety', () => {
    test('handles null nodes and edges', () => {
      const diff = compareLayouts(
        { viewport: null, nodes: null, edges: null, grid_settings: null, minimap_settings: null },
        { viewport: null, nodes: null, edges: null, grid_settings: null, minimap_settings: null }
      );

      expect(diff.totalChanges).toBe(0);
    });

    test('handles undefined nodes and edges', () => {
      const diff = compareLayouts({}, {});

      expect(diff.totalChanges).toBe(0);
    });

    test('compares null left nodes against populated right nodes', () => {
      const diff = compareLayouts(
        { nodes: null },
        { nodes: [{ id: 'n1', position: { x: 0, y: 0 } }] }
      );

      expect(diff.nodes.added).toHaveLength(1);
    });
  });

  describe('flattenDiffEntries', () => {
    test('collects all entries from summary', () => {
      const left: LayoutState = {
        viewport: { x: 0, y: 0, zoom: 1 },
        nodes: [{ id: 'n1', position: { x: 0, y: 0 } }],
        edges: [],
        grid_settings: { size: 20 },
        minimap_settings: null,
      };
      const right: LayoutState = {
        viewport: { x: 100, y: 0, zoom: 1 },
        nodes: [{ id: 'n2', position: { x: 10, y: 10 } }],
        edges: [{ id: 'e1', source: 'n2', target: 'n2' }],
        grid_settings: { size: 40 },
        minimap_settings: null,
      };
      const diff = compareLayouts(left, right);
      const flat = flattenDiffEntries(diff);

      expect(flat.length).toBeGreaterThanOrEqual(4);
      expect(flat.some((e) => e.category === 'node')).toBe(true);
      expect(flat.some((e) => e.category === 'edge')).toBe(true);
      expect(flat.some((e) => e.category === 'viewport')).toBe(true);
      expect(flat.some((e) => e.category === 'grid')).toBe(true);
    });

    test('returns empty array for identical layouts', () => {
      const diff = compareLayouts(emptyState, emptyState);
      const flat = flattenDiffEntries(diff);

      expect(flat).toHaveLength(0);
    });
  });
});
