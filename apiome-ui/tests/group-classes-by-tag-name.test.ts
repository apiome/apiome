import { computeTagGroupPlan } from '@/app/utils/group-classes-by-tag-name';

describe('computeTagGroupPlan', () => {
  const projectTags = [
    { id: 't1', name: 'Alpha', color: 'primary' },
    { id: 't2', name: 'Beta', color: 'success' },
    { id: 't3', name: 'Gamma', color: 'warning' },
  ];

  it('returns empty when no tag has two or more classes', () => {
    expect(
      computeTagGroupPlan(
        [
          { id: 'c1', tags: [{ id: 't1', tag_name: 'Alpha' }] },
          { id: 'c2', tags: [{ id: 't2', tag_name: 'Beta' }] },
        ],
        projectTags
      )
    ).toEqual([]);
  });

  it('groups two classes sharing one tag', () => {
    const plan = computeTagGroupPlan(
      [
        { id: 'c1', tags: [{ id: 't1', tag_name: 'Alpha' }] },
        { id: 'c2', tags: [{ id: 't1', tag_name: 'Alpha' }] },
      ],
      projectTags
    );
    expect(plan).toHaveLength(1);
    expect(plan[0]!.tagName).toBe('Alpha');
    expect(plan[0]!.tagId).toBe('t1');
    expect(new Set(plan[0]!.classIds)).toEqual(new Set(['c1', 'c2']));
  });

  it('assigns a multi-tagged class to the first tag name in A–Z order that still forms a multi-class group', () => {
    const tags = [
      { id: 'tA', name: 'Alpha', color: 'primary' },
      { id: 'tZ', name: 'Zeta', color: 'secondary' },
    ];
    const plan = computeTagGroupPlan(
      [
        {
          id: 'c1',
          tags: [
            { id: 'tZ', tag_name: 'Zeta' },
            { id: 'tA', tag_name: 'Alpha' },
          ],
        },
        { id: 'c2', tags: [{ id: 'tA', tag_name: 'Alpha' }] },
        { id: 'c3', tags: [{ id: 'tZ', tag_name: 'Zeta' }] },
        { id: 'c4', tags: [{ id: 'tZ', tag_name: 'Zeta' }] },
      ],
      tags
    );
    const alpha = plan.find((p) => p.tagName === 'Alpha');
    const zeta = plan.find((p) => p.tagName === 'Zeta');
    expect(alpha?.classIds.sort()).toEqual(['c1', 'c2']);
    expect(zeta?.classIds.sort()).toEqual(['c3', 'c4']);
  });

  it('merges classes that share the same display name via different tag ids', () => {
    const plan = computeTagGroupPlan(
      [
        { id: 'c1', tags: [{ id: 't1', tag_name: 'Shared' }] },
        { id: 'c2', tags: [{ id: 't1a', tag_name: 'Shared' }] },
      ],
      [
        { id: 't1', name: 'Shared', color: 'primary' },
        { id: 't1a', name: 'Shared', color: 'secondary' },
      ]
    );
    expect(plan).toHaveLength(1);
    expect(new Set(plan[0]!.classIds)).toEqual(new Set(['c1', 'c2']));
  });
});
