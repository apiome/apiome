import { buildGraphForSchemaMetrics } from '@/app/utils/schema-graph-from-classes';
import {
  computeSchemaMetrics,
  computeSchemaMetricsFromClasses,
  countConditionalSchemaCyclomaticInJsonSchema,
} from '@/app/utils/schema-metrics';

describe('countConditionalSchemaCyclomaticInJsonSchema (#612)', () => {
  it('returns 0 for empty or non-object roots', () => {
    expect(countConditionalSchemaCyclomaticInJsonSchema(undefined)).toBe(0);
    expect(countConditionalSchemaCyclomaticInJsonSchema(null)).toBe(0);
    expect(countConditionalSchemaCyclomaticInJsonSchema({})).toBe(0);
  });

  it('adds 1 for if without else and 2 when else is present', () => {
    expect(countConditionalSchemaCyclomaticInJsonSchema({ if: true, then: {} })).toBe(1);
    expect(countConditionalSchemaCyclomaticInJsonSchema({ if: {}, then: {}, else: {} })).toBe(2);
  });

  it('sums independent rules in allOf', () => {
    const doc = {
      allOf: [{ if: { const: 1 }, then: {} }, { if: { const: 2 }, then: {}, else: {} }],
    };
    expect(countConditionalSchemaCyclomaticInJsonSchema(doc)).toBe(3);
  });
});

describe('cognitive complexity per class (#610)', () => {
  it('sums properties and simple outgoing ref edges', () => {
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
    const byName = Object.fromEntries(m.cognitiveComplexityPerClass.map((c) => [c.className, c]));
    expect(byName.User).toMatchObject({
      score: 0,
      propertyContribution: 0,
      referenceContribution: 0,
      conditionalSchemaCyclomaticContribution: 0,
    });
    expect(byName.Post).toMatchObject({
      score: 2,
      propertyContribution: 1,
      referenceContribution: 1,
      conditionalSchemaCyclomaticContribution: 0,
    });
  });

  it('weights property-level anyOf refs higher than a single $ref', () => {
    const classes = [
      { id: 'u', name: 'User', properties: [], schema: {} },
      { id: 'p', name: 'Pet', properties: [], schema: {} },
      {
        id: 'o',
        name: 'OwnerRef',
        properties: [
          {
            id: 'p1',
            name: 'subject',
            data: JSON.stringify({
              anyOf: [{ $ref: '#/components/schemas/User' }, { $ref: '#/components/schemas/Pet' }],
            }),
          },
        ],
        schema: {},
      },
    ];
    const m = computeSchemaMetricsFromClasses(classes);
    const row = m.cognitiveComplexityPerClass.find((c) => c.className === 'OwnerRef');
    expect(row).toBeDefined();
    expect(row).toMatchObject({
      propertyContribution: 1,
      referenceContribution: 4,
      score: 5,
      conditionalSchemaCyclomaticContribution: 0,
    });
  });

  it('uses weight 2 for class-level oneOf edges from built graph', () => {
    const classes = [
      {
        id: 'a',
        name: 'Shape',
        properties: [],
        schema: {
          oneOf: [{ $ref: '#/components/schemas/Circle' }, { $ref: '#/components/schemas/Square' }],
        },
      },
      { id: 'b', name: 'Circle', properties: [], schema: {} },
      { id: 'c', name: 'Square', properties: [], schema: {} },
    ];
    const { nodes, edges } = buildGraphForSchemaMetrics(classes);
    const m = computeSchemaMetrics(nodes, edges);
    const shape = m.cognitiveComplexityPerClass.find((r) => r.className === 'Shape');
    expect(shape).toBeDefined();
    expect(shape!.referenceContribution).toBe(4);
    expect(shape!.conditionalSchemaCyclomaticContribution).toBe(0);
    expect(shape!.score).toBe(4);
  });

  it('adds conditional-schema cyclomatic to cognitive score and aggregate breakdown (#612)', () => {
    const classes = [
      { id: 'a', name: 'Plain', properties: [], schema: {} },
      {
        id: 'b',
        name: 'Rules',
        properties: [],
        schema: {
          if: { required: ['kind'], properties: { kind: { const: 'cat' } } },
          then: { required: ['lives'] },
          else: { required: ['scaleDepth'] },
        },
      },
    ];
    const m = computeSchemaMetricsFromClasses(classes);
    expect(m.conditionalSchemaCyclomaticTotal).toBe(2);
    expect(m.complexityBreakdown.some((r) => r.label.includes('Conditional schema cyclomatic'))).toBe(true);
    const rules = m.cognitiveComplexityPerClass.find((c) => c.className === 'Rules');
    expect(rules?.conditionalSchemaCyclomaticContribution).toBe(2);
    expect(rules?.score).toBe(2);
  });
});
