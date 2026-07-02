import { describe, it, expect } from '@jest/globals';
import type { Edge, Node } from '@xyflow/react';
import {
  mergePathsCanvasLayout,
  serializePathsCanvas,
} from '../../src/app/ade/studio/paths/lib/paths-canvas-persist';

describe('paths-canvas-persist', () => {
  it('mergePathsCanvasLayout applies saved positions by node id', () => {
    const computed: Node[] = [
      { id: 'op-1', type: 'operation', position: { x: 0, y: 0 }, data: {} },
      { id: 'param-1', type: 'parameter', position: { x: 10, y: 10 }, data: {} },
    ];
    const edges: Edge[] = [{ id: 'e1', source: 'op-1', target: 'param-1', data: {} }];
    const saved = {
      nodes: [{ id: 'op-1', position: { x: 99, y: 88 } }],
      edges: [],
      viewport: { x: 1, y: 2, zoom: 0.5 },
    };
    const out = mergePathsCanvasLayout(computed, edges, saved);
    expect(out.nodes[0].position).toEqual({ x: 99, y: 88 });
    expect(out.nodes[1].position).toEqual({ x: 10, y: 10 });
    expect(out.viewport).toEqual({ x: 1, y: 2, zoom: 0.5 });
  });

  it('serializePathsCanvas keeps layout fields and preserves viewport zoom', () => {
    const nodes: Node[] = [
      {
        id: 'n1',
        type: 'operation',
        position: { x: 1, y: 2 },
        data: { onDelete: () => {} },
      } as Node,
    ];
    const edges: Edge[] = [];
    const vp = { x: 3, y: 4, zoom: 0.25 };
    const ser = serializePathsCanvas(nodes, edges, vp);
    expect(ser.nodes[0]).not.toHaveProperty('data');
    expect(ser.viewport.zoom).toBe(0.25);
  });

  it('drops legacy "has" labels for path-has-operation edges from saved layout', () => {
    const computedNodes: Node[] = [
      { id: 'path-1', type: 'pathTemplate', position: { x: 0, y: 0 }, data: {} },
      { id: 'op-1', type: 'operation', position: { x: 10, y: 10 }, data: {} },
      { id: 'op-2', type: 'operation', position: { x: 20, y: 20 }, data: {} },
    ];
    const computedEdges: Edge[] = [
      {
        id: 'edge-path-op-1',
        source: 'path-1',
        sourceHandle: 'path-output',
        target: 'op-1',
        targetHandle: 'operation-input',
        data: { semantic: 'path-has-operation' },
      },
    ];
    const saved = {
      nodes: [],
      edges: [
        {
          id: 'edge-path-op-1',
          source: 'path-1',
          sourceHandle: 'path-output',
          target: 'op-1',
          targetHandle: 'operation-input',
          label: 'has',
          labelStyle: { fill: '#000' },
          labelBgStyle: { fill: '#fff' },
          data: { semantic: 'path-has-operation' },
        },
        {
          id: 'legacy-manual-path-op',
          source: 'path-1',
          sourceHandle: 'path-output',
          target: 'op-2',
          targetHandle: 'operation-input',
          label: 'has',
          labelStyle: { fill: '#000' },
          labelBgStyle: { fill: '#fff' },
        },
      ],
      viewport: { x: 0, y: 0, zoom: 1 },
    };

    const out = mergePathsCanvasLayout(computedNodes, computedEdges, saved);
    const computedEdgeOut = out.edges.find((e) => e.id === 'edge-path-op-1');
    const savedOnlyEdgeOut = out.edges.find((e) => e.id === 'legacy-manual-path-op');

    expect(computedEdgeOut?.label).toBeUndefined();
    expect(computedEdgeOut?.labelStyle).toBeUndefined();
    expect(computedEdgeOut?.labelBgStyle).toBeUndefined();

    expect(savedOnlyEdgeOut?.label).toBe('');
    expect(savedOnlyEdgeOut?.labelStyle).toBeUndefined();
    expect(savedOnlyEdgeOut?.labelBgStyle).toBeUndefined();
  });
});
