import {
  computeClassIdsPassingHideCriteria,
  groupNodeIdIsVisible,
} from '@/app/utils/canvas-display-visibility';

describe('canvas-display-visibility (#483)', () => {
  const groups = [
    { id: 'g1', nodeIds: ['a', 'b'] },
    { id: 'g2', nodeIds: ['c'] },
  ];

  const nodes = [
    { id: 'a', data: { properties: [{ name: 'x' }], schema: {} } },
    { id: 'b', data: { properties: [], schema: {} } },
    { id: 'c', data: { properties: [{ name: 'y' }], schema: { deprecated: true } } },
    { id: 'd', data: { properties: [{ name: 'z' }], schema: {} } },
  ];

  const connected = new Set(['a', 'b', 'c']);

  it('returns all class ids when no criteria enabled', () => {
    expect(
      computeClassIdsPassingHideCriteria(nodes, groups, connected, {
        hideEmptyClasses: false,
        hideUnconnectedClasses: false,
        hideDeprecatedClasses: false,
        hiddenGroupIds: new Set(),
      })
    ).toEqual(new Set(['a', 'b', 'c', 'd']));
  });

  it('hideEmptyClasses removes property-less classes', () => {
    expect(
      computeClassIdsPassingHideCriteria(nodes, groups, connected, {
        hideEmptyClasses: true,
        hideUnconnectedClasses: false,
        hideDeprecatedClasses: false,
        hiddenGroupIds: new Set(),
      })
    ).toEqual(new Set(['a', 'c', 'd']));
  });

  it('hideUnconnectedClasses removes nodes not in connected set', () => {
    expect(
      computeClassIdsPassingHideCriteria(nodes, groups, connected, {
        hideEmptyClasses: false,
        hideUnconnectedClasses: true,
        hideDeprecatedClasses: false,
        hiddenGroupIds: new Set(),
      })
    ).toEqual(new Set(['a', 'b', 'c']));
  });

  it('hideDeprecatedClasses removes schema.deprecated', () => {
    expect(
      computeClassIdsPassingHideCriteria(nodes, groups, connected, {
        hideEmptyClasses: false,
        hideUnconnectedClasses: false,
        hideDeprecatedClasses: true,
        hiddenGroupIds: new Set(),
      })
    ).toEqual(new Set(['a', 'b', 'd']));
  });

  it('hiddenGroupIds removes members of those groups', () => {
    expect(
      computeClassIdsPassingHideCriteria(nodes, groups, connected, {
        hideEmptyClasses: false,
        hideUnconnectedClasses: false,
        hideDeprecatedClasses: false,
        hiddenGroupIds: new Set(['g1']),
      })
    ).toEqual(new Set(['c', 'd']));
  });

  it('combines criteria as AND across rules', () => {
    expect(
      computeClassIdsPassingHideCriteria(nodes, groups, connected, {
        hideEmptyClasses: true,
        hideUnconnectedClasses: true,
        hideDeprecatedClasses: true,
        hiddenGroupIds: new Set(),
      })
    ).toEqual(new Set(['a']));
  });

  it('groupNodeIdIsVisible is true when any member is visible', () => {
    expect(groupNodeIdIsVisible(groups[0], new Set(['a']))).toBe(true);
    expect(groupNodeIdIsVisible(groups[0], new Set(['c']))).toBe(false);
    expect(groupNodeIdIsVisible(groups[1], new Set(['c']))).toBe(true);
  });
});
