import type { Edge, Node } from '@xyflow/react';
import {
  mapEdgesForLayoutSave,
  mapNodesForLayoutSave,
} from '../../src/app/ade/studio/lib/canvasLayoutPayload';

describe('canvasLayoutPayload', () => {
  it('maps class nodes with dimensions', () => {
    const nodes = [
      {
        id: 'c1',
        type: 'classNode',
        position: { x: 1, y: 2 },
        measured: { width: 100, height: 50 },
      },
    ] as Node[];
    const out = mapNodesForLayoutSave(nodes);
    expect(out).toHaveLength(1);
    expect(out[0]).toMatchObject({
      id: 'c1',
      type: 'classNode',
      position: { x: 1, y: 2 },
      dimensions: { width: 100, height: 50 },
    });
    expect(out[0].data).toBeUndefined();
  });

  it('maps group nodes with data payload', () => {
    const nodes = [
      {
        id: 'g1',
        type: 'groupNode',
        position: { x: 0, y: 0 },
        data: { name: 'G', color: '#fff', nodeIds: ['a'] },
      },
    ] as Node[];
    const out = mapNodesForLayoutSave(nodes);
    expect(out[0].data).toEqual({
      name: 'G',
      color: '#fff',
      nodeIds: ['a'],
      parentId: null,
    });
  });

  it('maps edges with handles', () => {
    const edges = [
      {
        id: 'e1',
        source: 'a',
        target: 'b',
        sourceHandle: 's',
        targetHandle: 't',
      },
    ] as Edge[];
    expect(mapEdgesForLayoutSave(edges)).toEqual([
      {
        id: 'e1',
        source: 'a',
        target: 'b',
        sourceHandle: 's',
        targetHandle: 't',
      },
    ]);
  });
});
