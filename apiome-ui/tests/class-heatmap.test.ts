/**
 * The class heatmap model (#560): measurements, the four 0–4 scales, labels and ordering.
 */

import {
  buildClassHeatmap,
  changeLevel,
  documentationLevel,
  heatLevels,
  heatmapCellSummary,
  heatmapValueLabel,
  sortCellsByHeat,
  type HeatmapClass,
} from '../src/app/utils/class-heatmap';

const NOW = new Date('2026-10-21T12:00:00Z');
const daysAgo = (n: number) => new Date(NOW.getTime() - n * 86_400_000).toISOString();

const CLASSES: HeatmapClass[] = [
  {
    id: 'order',
    name: 'Order',
    description: 'A customer order',
    updated_at: daysAgo(0),
    properties: [
      { id: 'o1', name: 'id', description: 'Identifier', data: { type: 'string' } },
      { id: 'o2', name: 'customer', description: 'Who', data: { $ref: '#/components/schemas/Customer' } },
      { id: 'o3', name: 'lines', description: null, data: { type: 'array', items: { $ref: '#/components/schemas/Line' } } },
      { id: 'o4', name: 'sku', description: '  ', data: { type: 'string' }, parent_id: 'o3' },
    ],
  },
  {
    id: 'customer',
    name: 'Customer',
    description: 'A buyer',
    updated_at: daysAgo(20),
    properties: [{ id: 'c1', name: 'name', description: 'Full name', data: { type: 'string' } }],
  },
  {
    id: 'line',
    name: 'Line',
    description: '',
    updated_at: daysAgo(400),
    properties: [{ id: 'l1', name: 'customer', description: null, data: { $ref: 'Customer' } }],
  },
  { id: 'empty', name: 'Empty', updated_at: null, created_at: null },
];

describe('buildClassHeatmap', () => {
  const cells = buildClassHeatmap(CLASSES, NOW);
  const byId = Object.fromEntries(cells.map((c) => [c.id, c]));

  it('counts properties, nesting depth and outgoing references into complexity', () => {
    expect(byId.order).toMatchObject({ propertyCount: 4, depth: 2, outgoingRefs: 2, complexity: 8 });
    expect(byId.empty).toMatchObject({ propertyCount: 0, depth: 0, outgoingRefs: 0, complexity: 0 });
  });

  it('counts distinct referencing classes, ignoring self and unknown targets', () => {
    expect(byId.customer.references).toBe(2);
    expect(byId.line.references).toBe(1);
    expect(byId.order.references).toBe(0);
  });

  it('measures age in whole days and treats a missing timestamp as unknown', () => {
    expect(byId.order.ageDays).toBe(0);
    expect(byId.customer.ageDays).toBe(20);
    expect(byId.empty).toMatchObject({ ageDays: null, modifiedAt: null });
  });

  it('falls back to created_at when updated_at is absent', () => {
    const [cell] = buildClassHeatmap([{ id: 'x', name: 'X', created_at: daysAgo(3) }], NOW);
    expect(cell.ageDays).toBe(3);
  });

  it('counts whitespace-only descriptions as missing', () => {
    expect(byId.order).toMatchObject({ documented: 3, documentable: 5, documentationPct: 60 });
    expect(byId.customer.documentationPct).toBe(100);
    expect(byId.line.documentationPct).toBe(0);
  });

  it('survives a parent_id cycle', () => {
    const [cell] = buildClassHeatmap(
      [{ id: 'k', name: 'K', properties: [{ id: 'a', name: 'a', parent_id: 'b' }, { id: 'b', name: 'b', parent_id: 'a' }] }],
      NOW
    );
    expect(cell.depth).toBe(2);
  });
});

describe('the scales', () => {
  it('ranks change by recency', () => {
    expect([0, 1, 5, 30, 60, 91, null].map((d) => changeLevel(d))).toEqual([4, 4, 3, 2, 1, 0, 0]);
  });

  it('ranks documentation by coverage', () => {
    expect([0, 10, 50, 99, 100].map(documentationLevel)).toEqual([0, 1, 2, 3, 4]);
  });

  it('scales complexity and references to the revision maximum', () => {
    const cells = buildClassHeatmap(CLASSES, NOW);
    const complexity = heatLevels(cells, 'complexity');
    expect(complexity.get('order')).toBe(4);
    expect(complexity.get('customer')).toBe(1); // 2 of 8
    expect(complexity.get('empty')).toBe(0);
    const refs = heatLevels(cells, 'references');
    expect([refs.get('customer'), refs.get('line'), refs.get('order')]).toEqual([4, 2, 0]);
  });

  it('is all cold for an empty revision or one with no references', () => {
    expect(heatLevels([], 'complexity').size).toBe(0);
    const cells = buildClassHeatmap([{ id: 'a', name: 'A' }], NOW);
    expect(heatLevels(cells, 'references').get('a')).toBe(0);
  });
});

describe('labels and ordering', () => {
  const cells = buildClassHeatmap(CLASSES, NOW);
  const byId = Object.fromEntries(cells.map((c) => [c.id, c]));

  it('prints a short value per metric', () => {
    expect(heatmapValueLabel(byId.order, 'complexity')).toBe('8 (4 props)');
    expect(heatmapValueLabel(byId.order, 'change')).toBe('Today');
    expect(heatmapValueLabel(byId.customer, 'change')).toBe('20 days ago');
    expect(heatmapValueLabel(byId.empty, 'change')).toBe('Unknown');
    expect(heatmapValueLabel(byId.line, 'references')).toBe('1 ref');
    expect(heatmapValueLabel(byId.order, 'documentation')).toBe('60%');
  });

  it('summarises all four measurements', () => {
    expect(heatmapCellSummary(byId.customer)).toBe(
      'Customer: complexity 2 (1 properties, depth 1, 0 outgoing references); changed 20 days ago; ' +
        'referenced by 2 classes; 2 of 2 items documented (100%).'
    );
  });

  it('sorts warmest first, then by raw value, then by name', () => {
    const order = (metric: Parameters<typeof heatLevels>[1]) =>
      sortCellsByHeat(cells, heatLevels(cells, metric), metric).map((c) => c.id);
    expect(order('complexity')).toEqual(['order', 'line', 'customer', 'empty']);
    expect(order('change')).toEqual(['order', 'customer', 'line', 'empty']);
    expect(order('references')).toEqual(['customer', 'line', 'empty', 'order']);
    expect(order('documentation')).toEqual(['customer', 'order', 'empty', 'line']);
  });
});
