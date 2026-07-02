import { buildStudioMetricsDigestForAi } from '../../lib/studio-metrics-digest-for-ai';
import {
  computeMaintainabilityIndexReport,
  computeTechnicalDebtMetricsReport,
  type SchemaMetricsResult,
} from '@/app/utils/schema-metrics';

function baseMetrics(over: Partial<SchemaMetricsResult> = {}): SchemaMetricsResult {
  const merged: SchemaMetricsResult = {
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
    conditionalSchemaCyclomaticTotal: 0,
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
    cognitiveComplexityPerClass: [
      {
        classId: '1',
        className: 'User',
        score: 7,
        propertyContribution: 5,
        referenceContribution: 2,
        conditionalSchemaCyclomaticContribution: 0,
      },
    ],
    dependencyGraphComplexity: {
      edgeCount: 2,
      deepestChainSteps: 1,
      circularGroupCount: 0,
      score: 6,
      scoreLabel: 'Low',
      breakdown: [
        { label: 'Dependency edges', value: 2, weight: 1.2, contribution: 2.4 },
        { label: 'Deepest ref chain (steps)', value: 1, weight: 4, contribution: 4 },
        { label: 'Circular groups (deps)', value: 0, weight: 6, contribution: 0 },
      ],
    },
    ...over,
  };
  merged.maintainabilityIndex =
    over.maintainabilityIndex ??
    computeMaintainabilityIndexReport({
      documentationCompletionPercentage: merged.documentationCompletionPercentage,
      namingCompliancePercentage: merged.namingCompliance.compliancePercentage,
      complexityScore: merged.complexityScore,
      dependencyGraphScore: merged.dependencyGraphComplexity.score,
      cognitiveComplexityPerClass: merged.cognitiveComplexityPerClass,
      averagePropertiesPerClass: merged.averagePropertiesPerClass,
      classCount: merged.classCount,
    });
  merged.technicalDebtMetrics =
    over.technicalDebtMetrics ??
    computeTechnicalDebtMetricsReport({
      documentationCompletionPercentage: merged.documentationCompletionPercentage,
      namingCompliancePercentage: merged.namingCompliance.compliancePercentage,
      complexityScore: merged.complexityScore,
      dependencyGraphScore: merged.dependencyGraphComplexity.score,
      conditionalSchemaCyclomaticTotal: merged.conditionalSchemaCyclomaticTotal,
      circularDependencyCount: merged.circularDependencyCount,
      deepestChainLength: merged.deepestChainLength,
      classCount: merged.classCount,
      isolatedClassCount: merged.isolatedClassIds.length,
      cognitiveComplexityPerClass: merged.cognitiveComplexityPerClass,
      averagePropertiesPerClass: merged.averagePropertiesPerClass,
    });
  return merged;
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
    expect(text).toContain('Per-class cognitive complexity');
    expect(text).toContain('User: 7 (props +5, refs +2, conditionals +0)');
    expect(text).toContain('Conditional schema cyclomatic (#612): 0');
    expect(text).toContain('Dependency graph complexity (#611)');
    expect(text).toContain('6/100');
    expect(text).toContain('Maintainability index (#613)');
    expect(text).toMatch(/Maintainability index \(#613\): \d+\/100/);
    expect(text).toContain('Technical debt (#614)');
    expect(text).toMatch(/Technical debt \(#614\): \d+\/100/);
  });

  it('includes overall schema quality score when provided (#255)', () => {
    const text = buildStudioMetricsDigestForAi(baseMetrics(), 72);
    expect(text).toContain('Overall schema quality score');
    expect(text).toContain('72');
  });
});
