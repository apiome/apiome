import { buildStudioMetricsDigestForAi } from '../../lib/studio-metrics-digest-for-ai';
import type { SchemaMetricsResult } from '@/app/utils/schema-metrics';

function baseMetrics(over: Partial<SchemaMetricsResult> = {}): SchemaMetricsResult {
  return {
    classCount: 2,
    totalProperties: 5,
    averagePropertiesPerClass: 2.5,
    relationshipCount: 1,
    hubClassIds: [],
    hubNames: ['User'],
    isolatedClassIds: [],
    isolatedNames: [],
    deepestChainLength: 2,
    circularDependencyCount: 0,
    circularSampleNames: [],
    circularDependencyNodeIds: [],
    complexityScore: 40,
    complexityLabel: 'Medium',
    complexityBreakdown: [],
    documentationCompletionPercentage: 50,
    classesMissingDocumentation: ['Order'],
    propertiesMissingDocumentation: [{ className: 'User', propertyName: 'email' }],
    namingCompliance: {
      classes: { pascal: 2, camel: 0, snake: 0, other: 0, total: 2 },
      properties: { pascal: 0, camel: 4, snake: 1, other: 0, total: 5 },
      compliancePercentage: 80,
      classesNonPascal: [],
      propertiesNonCamel: [{ className: 'User', propertyName: 'User_ID' }],
    },
    dependencyMetricsPerClass: [
      { classId: '1', className: 'User', inDegree: 0, outDegree: 2, betweenness: 0.1 },
    ],
    ...over,
  };
}

describe('buildStudioMetricsDigestForAi', () => {
  it('includes headline stats and gap samples', () => {
    const text = buildStudioMetricsDigestForAi(baseMetrics());
    expect(text).toContain('Classes: 2');
    expect(text).toContain('Documentation completion: 50%');
    expect(text).toContain('Order');
    expect(text).toContain('User.email');
    expect(text).toContain('User_ID');
    expect(text).toContain('Hub classes');
  });

  it('includes overall schema quality score when provided (#255)', () => {
    const text = buildStudioMetricsDigestForAi(baseMetrics(), 72);
    expect(text).toContain('Overall schema quality score');
    expect(text).toContain('72');
  });
});
