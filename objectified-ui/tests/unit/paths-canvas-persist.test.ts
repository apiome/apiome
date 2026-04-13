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
});
