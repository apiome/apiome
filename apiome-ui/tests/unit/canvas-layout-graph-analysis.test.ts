import type { Edge, Node } from '@xyflow/react';
import {
  analyzeCanvasLayoutGraph,
  canvasLayoutAnalysisDigest,
  remapStudioCanvasLayoutVertices,
} from '@/app/utils/canvas-layout-graph-analysis';

function classNode(id: string, name: string): Node {
  return {
    id,
    type: 'classNode',
    position: { x: 0, y: 0 },
    data: { name },
  };
}

describe('remapStudioCanvasLayoutVertices', () => {
  it('maps grouped class endpoints to the group node', () => {
    const nodes: Node[] = [
      classNode('a', 'A'),
      classNode('b', 'B'),
      {
        id: 'g1',
        type: 'groupNode',
        position: { x: 0, y: 0 },
        data: { nodeIds: ['b'], label: 'G1' },
      },
    ];
    const edges: Edge[] = [{ id: 'e1', source: 'a', target: 'b' }];
    const { vertexIds, directedEdges } = remapStudioCanvasLayoutVertices(nodes, edges);
    expect(vertexIds.sort()).toEqual(['a', 'g1']);
    expect(directedEdges).toEqual([{ source: 'a', target: 'g1' }]);
  });

  it('dedupes parallel edges after remap', () => {
    const nodes: Node[] = [classNode('a', 'A'), classNode('b', 'B')];
    const edges: Edge[] = [
      { id: 'e1', source: 'a', target: 'b' },
      { id: 'e2', source: 'a', target: 'b' },
    ];
    const { directedEdges } = remapStudioCanvasLayoutVertices(nodes, edges);
    expect(directedEdges).toEqual([{ source: 'a', target: 'b' }]);
  });
});

describe('analyzeCanvasLayoutGraph', () => {
  it('returns null when there are no class nodes', () => {
    const nodes: Node[] = [
      { id: 'g', type: 'groupNode', position: { x: 0, y: 0 }, data: { nodeIds: [] } },
    ];
    expect(analyzeCanvasLayoutGraph(nodes, [])).toBeNull();
  });

  it('detects a 2-node directed cycle as one SCC', () => {
    const nodes = [classNode('a', 'A'), classNode('b', 'B')];
    const edges: Edge[] = [
      { id: 'e1', source: 'a', target: 'b' },
      { id: 'e2', source: 'b', target: 'a' },
    ];
    const a = analyzeCanvasLayoutGraph(nodes, edges);
    expect(a).not.toBeNull();
    expect(a!.nonTrivialSccCount).toBe(1);
    expect(a!.stronglyConnectedComponents[0].memberIds.sort()).toEqual(['a', 'b']);
    expect(a!.recommendedDirection).toBe('LR');
    expect(a!.hierarchyRoots).toHaveLength(0);
  });

  it('finds a single hierarchy root in a DAG chain', () => {
    const nodes = [classNode('a', 'A'), classNode('b', 'B'), classNode('c', 'C')];
    const edges: Edge[] = [
      { id: 'e1', source: 'a', target: 'b' },
      { id: 'e2', source: 'b', target: 'c' },
    ];
    const a = analyzeCanvasLayoutGraph(nodes, edges, { deepestDependencyChainLength: 3 });
    expect(a!.hierarchyRoots.map((r) => r.id)).toEqual(['a']);
    expect(a!.nonTrivialSccCount).toBe(0);
    expect(a!.recommendedDirection).toBe('TB');
  });

  it('propagates deeper revisits through descendants for pseudo layering', () => {
    const nodes = [
      classNode('a', 'A'),
      classNode('b', 'B'),
      classNode('c', 'C'),
      classNode('d', 'D'),
      classNode('e', 'E'),
      classNode('f', 'F'),
    ];
    const edges: Edge[] = [
      { id: 'e1', source: 'a', target: 'b' },
      { id: 'e2', source: 'a', target: 'c' },
      { id: 'e3', source: 'b', target: 'd' },
      { id: 'e4', source: 'c', target: 'e' },
      { id: 'e5', source: 'e', target: 'd' },
      { id: 'e6', source: 'd', target: 'f' },
    ];
    const a = analyzeCanvasLayoutGraph(nodes, edges);
    expect(a).not.toBeNull();
    expect(a!.pseudoLayerDepth).toBe(5);
    expect(a!.pseudoLayerMaxWidth).toBe(2);
  });

  it('ranks hubs by total degree', () => {
    const nodes = [
      classNode('hub', 'Hub'),
      classNode('x', 'X'),
      classNode('y', 'Y'),
      classNode('z', 'Z'),
    ];
    const edges: Edge[] = [
      { id: 'e1', source: 'x', target: 'hub' },
      { id: 'e2', source: 'y', target: 'hub' },
      { id: 'e3', source: 'hub', target: 'z' },
    ];
    const a = analyzeCanvasLayoutGraph(nodes, edges);
    expect(a!.hubClasses[0].id).toBe('hub');
    expect(a!.hubClasses[0].totalDegree).toBe(3);
  });

  it('canvasLayoutAnalysisDigest is stable', () => {
    const nodes = [classNode('a', 'A')];
    const a1 = analyzeCanvasLayoutGraph(nodes, [])!;
    const a2 = analyzeCanvasLayoutGraph(nodes, [])!;
    expect(canvasLayoutAnalysisDigest(a1)).toBe(canvasLayoutAnalysisDigest(a2));
  });
});
