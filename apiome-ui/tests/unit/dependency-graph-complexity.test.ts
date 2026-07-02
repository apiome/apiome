import { describe, it, expect } from '@jest/globals';
import { buildGraphForSchemaMetrics } from '@/app/utils/schema-graph-from-classes';
import {
  computeDependencyGraphComplexityReport,
  computeSchemaMetricsFromClasses,
} from '@/app/utils/schema-metrics';

describe('dependency graph complexity (#611)', () => {
  it('exposes a 0–100 score and drivers on the dependency-only subgraph', () => {
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
    const dg = m.dependencyGraphComplexity;
    expect(dg.edgeCount).toBeGreaterThanOrEqual(1);
    expect(dg.deepestChainSteps).toBe(1);
    expect(dg.circularGroupCount).toBe(0);
    expect(dg.score).toBeGreaterThanOrEqual(0);
    expect(dg.score).toBeLessThanOrEqual(100);
    expect(['Low', 'Medium', 'High']).toContain(dg.scoreLabel);
    expect(dg.breakdown).toHaveLength(3);
    expect(dg.breakdown.map((b) => b.label)).toEqual([
      'Dependency edges',
      'Deepest ref chain (steps)',
      'Circular groups (deps)',
    ]);
  });

  it('counts cycle groups on dependency edges', () => {
    const classes = [
      {
        id: 'a',
        name: 'A',
        properties: [
          {
            id: 'p1',
            name: 'toB',
            data: JSON.stringify({ $ref: '#/components/schemas/B' }),
          },
        ],
        schema: {},
      },
      {
        id: 'b',
        name: 'B',
        properties: [
          {
            id: 'p2',
            name: 'toA',
            data: JSON.stringify({ $ref: '#/components/schemas/A' }),
          },
        ],
        schema: {},
      },
    ];
    const m = computeSchemaMetricsFromClasses(classes);
    expect(m.dependencyGraphComplexity.circularGroupCount).toBeGreaterThanOrEqual(1);
    expect(m.dependencyGraphComplexity.edgeCount).toBeGreaterThanOrEqual(2);
  });

  it('computeDependencyGraphComplexityReport handles an empty node set', () => {
    const { edges } = buildGraphForSchemaMetrics([]);
    const dg = computeDependencyGraphComplexityReport(new Set(), edges);
    expect(dg.edgeCount).toBe(0);
    expect(dg.deepestChainSteps).toBe(0);
    expect(dg.score).toBe(0);
    expect(dg.scoreLabel).toBe('Low');
  });
});
