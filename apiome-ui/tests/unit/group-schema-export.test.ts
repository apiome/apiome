import { expandClassesForGroupExport } from '../../src/app/utils/group-schema-export';

describe('expandClassesForGroupExport (#156)', () => {
  test('includes only roots when there are no refs', () => {
    const all = [
      { id: 'a', name: 'A', schema: { type: 'object' }, properties: [] },
      { id: 'b', name: 'B', schema: { type: 'object' }, properties: [] },
    ];
    expect(expandClassesForGroupExport(['a'], all)).toHaveLength(1);
    expect(expandClassesForGroupExport(['a'], all)[0].id).toBe('a');
  });

  test('pulls in transitively referenced classes', () => {
    const all = [
      {
        id: 'a',
        name: 'A',
        schema: { type: 'object' },
        properties: [{ data: { $ref: '#/components/schemas/B' } }],
      },
      { id: 'b', name: 'B', schema: { type: 'object' }, properties: [] },
      { id: 'c', name: 'C', schema: { type: 'object' }, properties: [] },
    ];
    const expanded = expandClassesForGroupExport(['a'], all);
    const ids = new Set(expanded.map((c) => c.id));
    expect(ids.has('a')).toBe(true);
    expect(ids.has('b')).toBe(true);
    expect(ids.has('c')).toBe(false);
  });
});
