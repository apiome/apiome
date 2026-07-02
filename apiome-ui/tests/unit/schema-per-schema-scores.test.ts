import { computePerSchemaScoresFromClasses, computePerSchemaScores } from '@/app/utils/schema-metrics';
import { buildGraphForSchemaMetrics } from '@/app/utils/schema-graph-from-classes';

describe('computePerSchemaScores / computePerSchemaScoresFromClasses (#250)', () => {
  it('returns one row per class with scores in 0–100', () => {
    const classes = [
      {
        id: 'a',
        name: 'UserAccount',
        description: 'A user',
        properties: [
          { name: 'email', description: 'Primary email', data: JSON.stringify({ type: 'string' }) },
        ],
        schema: {},
      },
      {
        id: 'b',
        name: 'BlogPost',
        properties: [{ name: 'title', data: JSON.stringify({ type: 'string' }) }],
        schema: {},
      },
    ];
    const rows = computePerSchemaScoresFromClasses(classes);
    expect(rows).toHaveLength(2);
    for (const r of rows) {
      expect(r.documentationScore).toBeGreaterThanOrEqual(0);
      expect(r.documentationScore).toBeLessThanOrEqual(100);
      expect(r.namingScore).toBeGreaterThanOrEqual(0);
      expect(r.namingScore).toBeLessThanOrEqual(100);
      expect(r.complexityScore).toBeGreaterThanOrEqual(0);
      expect(r.complexityScore).toBeLessThanOrEqual(100);
      expect(['Low', 'Medium', 'High']).toContain(r.complexityLabel);
    }
    const names = rows.map((r) => r.className).sort();
    expect(names).toEqual(['BlogPost', 'UserAccount']);
  });

  it('matches computePerSchemaScores on built graph', () => {
    const classes = [
      { id: 'x', name: 'Order', properties: [], schema: {} },
    ];
    const { nodes, edges } = buildGraphForSchemaMetrics(classes);
    const a = computePerSchemaScoresFromClasses(classes);
    const b = computePerSchemaScores(nodes, edges);
    expect(a).toEqual(b);
  });

  it('returns empty array for no classes', () => {
    expect(computePerSchemaScoresFromClasses([])).toEqual([]);
  });
});
