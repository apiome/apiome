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
    expect(m.dependencyGraphComplexity.edgeCount).toBeGreaterThanOrEqual(1);
    expect(m.dependencyGraphComplexity.deepestChainSteps).toBe(1);
    const byName = Object.fromEntries(m.cognitiveComplexityPerClass.map((c) => [c.className, c]));
    expect(byName.Post?.score).toBe(2);
    expect(byName.User?.score).toBe(0);
    expect(m.maintainabilityIndex.score).toBeGreaterThanOrEqual(0);
    expect(m.maintainabilityIndex.score).toBeLessThanOrEqual(100);
  });
});
