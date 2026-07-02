import {
  MAX_CANVAS_GROUP_DEPTH,
  collectAllNodeIdsInGroupSubtree,
  collectDescendantGroupIds,
  collectSubtreeGroupIds,
  findInnermostGroupAtPosition,
  getGroupDepth,
  groupById,
  isStrictDescendantGroup,
  maxChildGroupChainLength,
  sortGroupsParentsBeforeChildren,
  wouldNestExceedMaxDepth,
} from '@/app/utils/canvas-nested-groups';
import type { CanvasGroup } from '@/app/ade/studio/StudioContext';

describe('canvas-nested-groups (#155)', () => {
  const tree: CanvasGroup[] = [
    { id: 'r', name: 'R', color: 'blue', nodeIds: ['a'], parentId: null, position: { x: 0, y: 0 }, dimensions: { width: 400, height: 300 } },
    { id: 'c1', name: 'C1', color: 'blue', nodeIds: ['b'], parentId: 'r', position: { x: 0, y: 0 }, dimensions: { width: 200, height: 200 } },
    { id: 'c2', name: 'C2', color: 'blue', nodeIds: [], parentId: 'c1', position: { x: 0, y: 0 }, dimensions: { width: 100, height: 100 } },
  ];

  it('getGroupDepth counts from root', () => {
    const byId = groupById(tree);
    expect(getGroupDepth('r', byId)).toBe(1);
    expect(getGroupDepth('c1', byId)).toBe(2);
    expect(getGroupDepth('c2', byId)).toBe(3);
  });

  it('maxChildGroupChainLength measures edges below a node', () => {
    expect(maxChildGroupChainLength('c2', tree)).toBe(0);
    expect(maxChildGroupChainLength('c1', tree)).toBe(1);
    expect(maxChildGroupChainLength('r', tree)).toBe(2);
  });

  it('wouldNestExceedMaxDepth allows three levels and rejects a fourth', () => {
    expect(wouldNestExceedMaxDepth('c2', null, tree)).toBe(false);
    const chain3: CanvasGroup[] = [
      { id: 'g1', name: '', color: 'x', nodeIds: [], parentId: null, position: { x: 0, y: 0 }, dimensions: { width: 1, height: 1 } },
      { id: 'g2', name: '', color: 'x', nodeIds: [], parentId: 'g1', position: { x: 0, y: 0 }, dimensions: { width: 1, height: 1 } },
      { id: 'g3', name: '', color: 'x', nodeIds: [], parentId: 'g2', position: { x: 0, y: 0 }, dimensions: { width: 1, height: 1 } },
    ];
    const leaf: CanvasGroup = {
      id: 'leaf',
      name: '',
      color: 'x',
      nodeIds: [],
      parentId: null,
      position: { x: 0, y: 0 },
      dimensions: { width: 1, height: 1 },
    };
    expect(wouldNestExceedMaxDepth('leaf', 'g3', [...chain3, leaf])).toBe(true);
  });

  it('isStrictDescendantGroup detects ancestry', () => {
    const byId = groupById(tree);
    expect(isStrictDescendantGroup('r', 'c1', byId)).toBe(true);
    expect(isStrictDescendantGroup('r', 'c2', byId)).toBe(true);
    expect(isStrictDescendantGroup('c1', 'r', byId)).toBe(false);
    expect(isStrictDescendantGroup('c1', 'c2', byId)).toBe(true);
  });

  it('collectDescendantGroupIds and collectSubtreeGroupIds', () => {
    expect([...collectDescendantGroupIds('r', tree)].sort()).toEqual(['c1', 'c2']);
    expect([...collectSubtreeGroupIds('r', tree)].sort()).toEqual(['c1', 'c2', 'r']);
  });

  it('collectAllNodeIdsInGroupSubtree dedupes class ids', () => {
    expect(collectAllNodeIdsInGroupSubtree('r', tree).sort()).toEqual(['a', 'b']);
  });

  it('sortGroupsParentsBeforeChildren orders parents first', () => {
    const shuffled = [tree[2], tree[0], tree[1]];
    const sorted = sortGroupsParentsBeforeChildren(shuffled);
    expect(sorted.map((g) => g.id)).toEqual(['r', 'c1', 'c2']);
  });

  it('findInnermostGroupAtPosition picks smallest containing frame', () => {
    const nodes = [
      { id: 'big', type: 'groupNode' as const, position: { x: 0, y: 0 }, style: { width: 400, height: 300 } },
      { id: 'small', type: 'groupNode' as const, position: { x: 50, y: 50 }, style: { width: 80, height: 60 } },
    ];
    expect(findInnermostGroupAtPosition(90, 80, nodes, new Set())).toBe('small');
    expect(findInnermostGroupAtPosition(5, 5, nodes, new Set(['small']))).toBe('big');
  });

  it('MAX_CANVAS_GROUP_DEPTH is 3', () => {
    expect(MAX_CANVAS_GROUP_DEPTH).toBe(3);
  });
});
