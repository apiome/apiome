import { buildGraphForSchemaMetrics } from '@/app/utils/schema-graph-from-classes';
import { computeSchemaMetricsFromClasses } from '@/app/utils/schema-metrics';

describe('schema-graph-from-classes / computeSchemaMetricsFromClasses', () => {
  it('builds nodes and dependency edges for metrics', () => {
    const classes = [
      { id: 'a', name: 'User', properties: [], schema: {} },
      {
        id: 'b',
        name: 'Post',
        properties: [
          {
            id: 'p1',
            name: 'author',
            data: JSON.stringify({ $ref: '#/components/schemas/User' }),
          },
        ],
        schema: {},
      },
    ];
    const { nodes, edges } = buildGraphForSchemaMetrics(classes);
    expect(nodes).toHaveLength(2);
    expect(edges.some((e) => e.id.startsWith('prop-'))).toBe(true);
  });

  it('computes aggregate metrics consistent with graph', () => {
    const classes = [
      { id: 'a', name: 'User', properties: [], schema: {} },
      {
        id: 'b',
        name: 'Post',
        properties: [
          {
            id: 'p1',
            name: 'author',
            data: JSON.stringify({ $ref: '#/components/schemas/User' }),
          },
        ],
        schema: {},
      },
    ];
    const m = computeSchemaMetricsFromClasses(classes);
    expect(m.classCount).toBe(2);
    expect(m.relationshipCount).toBeGreaterThan(0);
    expect(m.complexityScore).toBeGreaterThanOrEqual(0);
    expect(m.complexityScore).toBeLessThanOrEqual(100);
  });
});
