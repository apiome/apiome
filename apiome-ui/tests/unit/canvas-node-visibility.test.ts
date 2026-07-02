import {
  getVisibleGroupIdsForSelectedClasses,
  getVisibleNodeIdsForIsolateSelection,
} from '@/app/utils/canvas-node-visibility';

describe('canvas-node-visibility (#482)', () => {
  const groups = [
    { id: 'g1', nodeIds: ['a', 'b'] },
    { id: 'g2', nodeIds: ['c'] },
    { id: 'g3', nodeIds: [] },
  ];

  it('getVisibleGroupIdsForSelectedClasses returns groups that contain a selected class', () => {
    expect(getVisibleGroupIdsForSelectedClasses(groups, new Set(['a']))).toEqual(new Set(['g1']));
    expect(getVisibleGroupIdsForSelectedClasses(groups, new Set(['a', 'c']))).toEqual(
      new Set(['g1', 'g2'])
    );
    expect(getVisibleGroupIdsForSelectedClasses(groups, new Set())).toEqual(new Set());
    expect(getVisibleGroupIdsForSelectedClasses(groups, new Set(['z']))).toEqual(new Set());
  });

  it('getVisibleNodeIdsForIsolateSelection unions selected classes and enclosing group ids', () => {
    expect(getVisibleNodeIdsForIsolateSelection(groups, new Set(['b']))).toEqual(
      new Set(['b', 'g1'])
    );
    expect(getVisibleNodeIdsForIsolateSelection(groups, new Set(['c']))).toEqual(
      new Set(['c', 'g2'])
    );
  });

  it('getVisibleNodeIdsForIsolateSelection includes ancestor frames for nested groups (#155)', () => {
    const nested = [
      { id: 'g1', nodeIds: ['a'], parentId: null as string | null },
      { id: 'g2', nodeIds: ['c'], parentId: 'g1' },
    ];
    expect(getVisibleNodeIdsForIsolateSelection(nested, new Set(['c']))).toEqual(
      new Set(['c', 'g2', 'g1'])
    );
  });
});
