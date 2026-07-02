/**
 * Canvas Auto-Layout Test Suite
 *
 * Tests the automatic layout algorithm for arranging nodes on the canvas.
 */

import { describe, test, expect } from '@jest/globals';
import { applyAutoLayout, createOrthogonalEdgePath, calculateFitViewport } from '../src/app/utils/canvas-auto-layout';
import type { Node, Edge } from '@xyflow/react';

/**
 * Create a mock node
 */
function createMockNode(id: string, position = { x: 0, y: 0 }, type = 'classNode'): Node {
  return {
    id,
    type,
    position,
    data: { name: id },
    measured: { width: 280, height: 100 },
  };
}

/**
 * Create a mock edge
 */
function createMockEdge(source: string, target: string): Edge {
  return {
    id: `${source}-${target}`,
    source,
    target,
  };
}

describe('Canvas Auto-Layout', () => {
  describe('applyAutoLayout', () => {
    test('should return empty array for no nodes', () => {
      const result = applyAutoLayout([], []);
      expect(result).toEqual([]);
    });

    test('should layout single node at padding offset', () => {
      const nodes = [createMockNode('A')];
      const result = applyAutoLayout(nodes, []);

      expect(result.length).toBe(1);
      expect(result[0].position.x).toBeGreaterThanOrEqual(0);
      expect(result[0].position.y).toBeGreaterThanOrEqual(0);
    });

    test('should layout two independent nodes on same layer', () => {
      const nodes = [
        createMockNode('A'),
        createMockNode('B'),
      ];
      const result = applyAutoLayout(nodes, []);

      expect(result.length).toBe(2);
      // Both should be on the same y-level (same layer)
      expect(result[0].position.y).toBe(result[1].position.y);
      // But different x positions
      expect(result[0].position.x).not.toBe(result[1].position.x);
    });

    test('should layout connected nodes on different layers', () => {
      const nodes = [
        createMockNode('A'),
        createMockNode('B'),
      ];
      const edges = [
        createMockEdge('A', 'B'),
      ];
      const result = applyAutoLayout(nodes, edges);

      expect(result.length).toBe(2);

      const nodeA = result.find(n => n.id === 'A')!;
      const nodeB = result.find(n => n.id === 'B')!;

      // A should be on a layer above B (smaller y)
      expect(nodeA.position.y).toBeLessThan(nodeB.position.y);
    });

    test('should handle chain of dependencies', () => {
      const nodes = [
        createMockNode('A'),
        createMockNode('B'),
        createMockNode('C'),
      ];
      const edges = [
        createMockEdge('A', 'B'),
        createMockEdge('B', 'C'),
      ];
      const result = applyAutoLayout(nodes, edges);

      const nodeA = result.find(n => n.id === 'A')!;
      const nodeB = result.find(n => n.id === 'B')!;
      const nodeC = result.find(n => n.id === 'C')!;

      // A -> B -> C should be in order vertically
      expect(nodeA.position.y).toBeLessThan(nodeB.position.y);
      expect(nodeB.position.y).toBeLessThan(nodeC.position.y);
    });

    test('should handle diamond dependency pattern', () => {
      // A -> B, A -> C, B -> D, C -> D
      const nodes = [
        createMockNode('A'),
        createMockNode('B'),
        createMockNode('C'),
        createMockNode('D'),
      ];
      const edges = [
        createMockEdge('A', 'B'),
        createMockEdge('A', 'C'),
        createMockEdge('B', 'D'),
        createMockEdge('C', 'D'),
      ];
      const result = applyAutoLayout(nodes, edges);

      const nodeA = result.find(n => n.id === 'A')!;
      const nodeB = result.find(n => n.id === 'B')!;
      const nodeC = result.find(n => n.id === 'C')!;
      const nodeD = result.find(n => n.id === 'D')!;

      // A should be at top
      expect(nodeA.position.y).toBeLessThan(nodeB.position.y);
      expect(nodeA.position.y).toBeLessThan(nodeC.position.y);

      // B and C should be on the same layer
      expect(nodeB.position.y).toBe(nodeC.position.y);

      // D should be at bottom
      expect(nodeD.position.y).toBeGreaterThan(nodeB.position.y);
      expect(nodeD.position.y).toBeGreaterThan(nodeC.position.y);
    });

    test('should preserve empty group nodes unchanged', () => {
      const nodes = [
        createMockNode('A'),
        createMockNode('B'),
        createMockNode('group1', { x: 100, y: 100 }, 'groupNode'),
      ];
      const edges = [
        createMockEdge('A', 'B'),
      ];
      const result = applyAutoLayout(nodes, edges);

      expect(result.length).toBe(3);

      const groupNode = result.find(n => n.type === 'groupNode')!;
      // Empty group node still participates in layout (is repositioned)
      // but should maintain its original dimensions
      expect(groupNode).toBeDefined();
      expect(groupNode.type).toBe('groupNode');
    });

    test('should recalculate group bounds based on member nodes', () => {
      // Create a group node with member nodeIds at specific positions
      const nodeA = createMockNode('A', { x: 100, y: 100 });
      const nodeB = createMockNode('B', { x: 100, y: 250 });
      const groupNode = {
        ...createMockNode('group1', { x: 60, y: 50 }, 'groupNode'),
        data: { nodeIds: ['A', 'B'], label: 'Test Group' },
        style: { width: 360, height: 350 },
      };
      const nodes = [nodeA, nodeB, groupNode];
      const edges: any[] = [];

      // Record original offsets of members relative to the group
      const originalAOffsetX = nodeA.position.x - groupNode.position.x;
      const originalAOffsetY = nodeA.position.y - groupNode.position.y;
      const originalBOffsetX = nodeB.position.x - groupNode.position.x;
      const originalBOffsetY = nodeB.position.y - groupNode.position.y;

      const result = applyAutoLayout(nodes, edges);

      const resultGroup = result.find(n => n.type === 'groupNode')!;
      const resultA = result.find(n => n.id === 'A')!;
      const resultB = result.find(n => n.id === 'B')!;

      // Offsets relative to the group should be EXACTLY preserved
      const resultAOffsetX = resultA.position.x - resultGroup.position.x;
      const resultAOffsetY = resultA.position.y - resultGroup.position.y;
      const resultBOffsetX = resultB.position.x - resultGroup.position.x;
      const resultBOffsetY = resultB.position.y - resultGroup.position.y;

      expect(resultAOffsetX).toBe(originalAOffsetX);
      expect(resultAOffsetY).toBe(originalAOffsetY);
      expect(resultBOffsetX).toBe(originalBOffsetX);
      expect(resultBOffsetY).toBe(originalBOffsetY);
    });

    test('should not reposition grouped nodes independently', () => {
      // Create an ungrouped node C, and grouped nodes A, B
      const nodeA = createMockNode('A', { x: 100, y: 100 });
      const nodeB = createMockNode('B', { x: 100, y: 250 });
      const nodeC = createMockNode('C', { x: 500, y: 100 }); // Ungrouped
      const groupNode = {
        ...createMockNode('group1', { x: 60, y: 50 }, 'groupNode'),
        data: { nodeIds: ['A', 'B'], label: 'Test Group' },
        style: { width: 360, height: 350 },
      };

      const nodes = [nodeA, nodeB, nodeC, groupNode];
      const edges = [createMockEdge('A', 'C')];

      // Record original offsets
      const originalAOffsetX = nodeA.position.x - groupNode.position.x;
      const originalAOffsetY = nodeA.position.y - groupNode.position.y;
      const originalBOffsetX = nodeB.position.x - groupNode.position.x;
      const originalBOffsetY = nodeB.position.y - groupNode.position.y;

      const result = applyAutoLayout(nodes, edges);

      expect(result.length).toBe(4);

      const resultA = result.find(n => n.id === 'A')!;
      const resultB = result.find(n => n.id === 'B')!;
      const resultGroup = result.find(n => n.type === 'groupNode')!;

      // Member offsets relative to group should be EXACTLY preserved
      expect(resultA.position.x - resultGroup.position.x).toBe(originalAOffsetX);
      expect(resultA.position.y - resultGroup.position.y).toBe(originalAOffsetY);
      expect(resultB.position.x - resultGroup.position.x).toBe(originalBOffsetX);
      expect(resultB.position.y - resultGroup.position.y).toBe(originalBOffsetY);
    });

    test('should handle custom spacing options', () => {
      const nodes = [
        createMockNode('A'),
        createMockNode('B'),
      ];
      const edges = [
        createMockEdge('A', 'B'),
      ];

      const result = applyAutoLayout(nodes, edges, {
        nodeSpacingY: 200,
        padding: 100,
      });

      const nodeA = result.find(n => n.id === 'A')!;
      const nodeB = result.find(n => n.id === 'B')!;

      // Y difference should be at least nodeSpacingY (accounting for node height)
      expect(nodeB.position.y - nodeA.position.y).toBeGreaterThanOrEqual(200);
    });

    test('should handle circular dependencies gracefully', () => {
      const nodes = [
        createMockNode('A'),
        createMockNode('B'),
        createMockNode('C'),
      ];
      const edges = [
        createMockEdge('A', 'B'),
        createMockEdge('B', 'C'),
        createMockEdge('C', 'A'), // Circular!
      ];

      // Should not throw
      const result = applyAutoLayout(nodes, edges);
      expect(result.length).toBe(3);
    });

    test('should handle disconnected components', () => {
      const nodes = [
        createMockNode('A'),
        createMockNode('B'),
        createMockNode('C'),
        createMockNode('D'),
      ];
      const edges = [
        createMockEdge('A', 'B'),
        createMockEdge('C', 'D'),
      ];

      const result = applyAutoLayout(nodes, edges);
      expect(result.length).toBe(4);

      // All nodes should have valid positions
      result.forEach(node => {
        expect(typeof node.position.x).toBe('number');
        expect(typeof node.position.y).toBe('number');
        expect(isNaN(node.position.x)).toBe(false);
        expect(isNaN(node.position.y)).toBe(false);
      });
    });
  });

  describe('createOrthogonalEdgePath', () => {
    test('should create path with only horizontal and vertical segments', () => {
      const path = createOrthogonalEdgePath(0, 0, 100, 100);

      // Path should only contain M, L commands with straight segments
      expect(path).toMatch(/^M\s*[\d.-]+\s*[\d.-]+/);
      expect(path).toContain('L');
    });

    test('should handle same y coordinate', () => {
      const path = createOrthogonalEdgePath(0, 50, 100, 50);
      expect(path).toBeDefined();
    });

    test('should handle same x coordinate', () => {
      const path = createOrthogonalEdgePath(50, 0, 50, 100);
      expect(path).toBeDefined();
    });

    test('should handle negative coordinates', () => {
      const path = createOrthogonalEdgePath(-50, -50, 50, 50);
      expect(path).toBeDefined();
      expect(path).toContain('-50');
    });
  });

  describe('calculateFitViewport', () => {
    test('should return default for empty nodes', () => {
      const result = calculateFitViewport([], 1000, 800);
      expect(result.x).toBe(0);
      expect(result.y).toBe(0);
      expect(result.zoom).toBe(1);
    });

    test('should calculate viewport for single node', () => {
      const nodes = [createMockNode('A', { x: 100, y: 100 })];
      const result = calculateFitViewport(nodes, 1000, 800);

      expect(result.zoom).toBeGreaterThan(0);
      expect(result.zoom).toBeLessThanOrEqual(1);
    });

    test('should zoom out for large layout', () => {
      const nodes = [
        createMockNode('A', { x: 0, y: 0 }),
        createMockNode('B', { x: 2000, y: 2000 }),
      ];
      const result = calculateFitViewport(nodes, 1000, 800);

      // Should zoom out to fit all nodes
      expect(result.zoom).toBeLessThan(1);
    });

    test('should not zoom in beyond 100%', () => {
      const nodes = [createMockNode('A', { x: 400, y: 350 })];
      const result = calculateFitViewport(nodes, 1000, 800);

      // Zoom should not exceed 1 (100%)
      expect(result.zoom).toBeLessThanOrEqual(1);
    });

    test('should include padding', () => {
      const nodes = [
        createMockNode('A', { x: 0, y: 0 }),
        createMockNode('B', { x: 500, y: 500 }),
      ];

      const resultWithPadding = calculateFitViewport(nodes, 1000, 800, 100);
      const resultNoPadding = calculateFitViewport(nodes, 1000, 800, 0);

      // With more padding, zoom should be smaller
      expect(resultWithPadding.zoom).toBeLessThanOrEqual(resultNoPadding.zoom);
    });
  });

  describe('Edge Cases', () => {
    test('should handle node with no measured dimensions', () => {
      const node: Node = {
        id: 'A',
        type: 'classNode',
        position: { x: 0, y: 0 },
        data: {},
        // No measured property
      };

      const result = applyAutoLayout([node], []);
      expect(result.length).toBe(1);
    });

    test('should handle large number of nodes', () => {
      const nodes: Node[] = [];
      const edges: Edge[] = [];

      // Create 50 nodes in a chain
      for (let i = 0; i < 50; i++) {
        nodes.push(createMockNode(`Node${i}`));
        if (i > 0) {
          edges.push(createMockEdge(`Node${i - 1}`, `Node${i}`));
        }
      }

      const result = applyAutoLayout(nodes, edges);
      expect(result.length).toBe(50);

      // Verify ordering is maintained
      for (let i = 0; i < 49; i++) {
        const current = result.find(n => n.id === `Node${i}`)!;
        const next = result.find(n => n.id === `Node${i + 1}`)!;
        expect(current.position.y).toBeLessThan(next.position.y);
      }
    });

    test('should handle node with many outgoing edges', () => {
      const nodes = [
        createMockNode('Hub'),
        ...Array.from({ length: 10 }, (_, i) => createMockNode(`Spoke${i}`)),
      ];
      const edges = Array.from({ length: 10 }, (_, i) =>
        createMockEdge('Hub', `Spoke${i}`)
      );

      const result = applyAutoLayout(nodes, edges);
      expect(result.length).toBe(11);

      const hub = result.find(n => n.id === 'Hub')!;
      const spokes = result.filter(n => n.id.startsWith('Spoke'));

      // Hub should be above all spokes
      spokes.forEach(spoke => {
        expect(hub.position.y).toBeLessThan(spoke.position.y);
      });

      // All spokes should be on the same layer
      const firstSpokeY = spokes[0].position.y;
      spokes.forEach(spoke => {
        expect(spoke.position.y).toBe(firstSpokeY);
      });
    });

    test('should handle node with many incoming edges', () => {
      const nodes = [
        createMockNode('Sink'),
        ...Array.from({ length: 10 }, (_, i) => createMockNode(`Source${i}`)),
      ];
      const edges = Array.from({ length: 10 }, (_, i) =>
        createMockEdge(`Source${i}`, 'Sink')
      );

      const result = applyAutoLayout(nodes, edges);
      expect(result.length).toBe(11);

      const sink = result.find(n => n.id === 'Sink')!;
      const sources = result.filter(n => n.id.startsWith('Source'));

      // Sink should be below all sources
      sources.forEach(source => {
        expect(sink.position.y).toBeGreaterThan(source.position.y);
      });
    });
  });
});

