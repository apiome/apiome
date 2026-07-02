import { describe, it, expect } from '@jest/globals';
import {
  computeMaintainabilityIndexReport,
  computeTechnicalDebtMetricsReport,
  type SchemaMetricsResult,
} from '@/app/utils/schema-metrics';
import { computeOverallSchemaQualityScore, computeOverallSchemaQualityDetail } from '@/app/utils/overall-schema-quality';

function makeMinimalMetrics(overrides: Partial<SchemaMetricsResult> = {}): SchemaMetricsResult {
  const merged: SchemaMetricsResult = {
    classCount: 3,
    totalProperties: 9,
    averagePropertiesPerClass: 3,
    relationshipCount: 2,
    hubClassIds: [],
    hubNames: [],
    isolatedClassIds: [],
    isolatedNames: [],
    deepestChainLength: 2,
    circularDependencyCount: 0,
    circularSampleNames: [],
    circularDependencyNodeIds: [],
    complexityScore: 30,
    complexityLabel: 'Low',
    complexityBreakdown: [{ label: 'Classes', value: 3, weight: 1.5, contribution: 4.5 }],
    conditionalSchemaCyclomaticTotal: 0,
    documentationCompletionPercentage: 80,
    classesMissingDocumentation: [],
    propertiesMissingDocumentation: [],
    namingCompliance: {
      classes: { pascal: 3, camel: 0, snake: 0, other: 0, total: 3 },
      properties: { pascal: 0, camel: 9, snake: 0, other: 0, total: 9 },
      compliancePercentage: 90,
      classesNonPascal: [],
      propertiesNonCamel: [],
    },
    dependencyMetricsPerClass: [],
    cognitiveComplexityPerClass: [],
    dependencyGraphComplexity: {
      edgeCount: 0,
      deepestChainSteps: 0,
      circularGroupCount: 0,
      score: 0,
      scoreLabel: 'Low',
      breakdown: [
        { label: 'Dependency edges', value: 0, weight: 1.2, contribution: 0 },
        { label: 'Deepest ref chain (steps)', value: 0, weight: 4, contribution: 0 },
        { label: 'Circular groups (deps)', value: 0, weight: 6, contribution: 0 },
      ],
    },
    ...overrides,
  };
  merged.maintainabilityIndex =
    overrides.maintainabilityIndex ??
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
    overrides.technicalDebtMetrics ??
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

describe('computeOverallSchemaQualityScore (#245)', () => {
  it('returns 0–100 integer', () => {
    const m = makeMinimalMetrics();
    const s = computeOverallSchemaQualityScore(m, { overallScore: 80, edgeCrossingCount: 0, nodeSpacingUniformityScore: 80, layoutSymmetryScore: 80, visualBalanceScore: 80 });
    expect(s).toBeGreaterThanOrEqual(0);
    expect(s).toBeLessThanOrEqual(100);
    expect(Number.isInteger(s)).toBe(true);
  });

  it('is 100 when all inputs are ideal and complexity is minimal', () => {
    const m = makeMinimalMetrics({
      complexityScore: 0,
      documentationCompletionPercentage: 100,
      namingCompliance: {
        classes: { pascal: 1, camel: 0, snake: 0, other: 0, total: 1 },
        properties: { pascal: 0, camel: 0, snake: 0, other: 0, total: 0 },
        compliancePercentage: 100,
        classesNonPascal: [],
        propertiesNonCamel: [],
      },
    });
    const s = computeOverallSchemaQualityScore(m, {
      overallScore: 100,
      edgeCrossingCount: 0,
      nodeSpacingUniformityScore: 100,
      layoutSymmetryScore: 100,
      visualBalanceScore: 100,
    });
    expect(s).toBe(100);
  });

  it('omitting layout renormalizes weights across docs, naming, and inverted complexity', () => {
    const m = makeMinimalMetrics({
      complexityScore: 0,
      documentationCompletionPercentage: 100,
      namingCompliance: {
        classes: { pascal: 1, camel: 0, snake: 0, other: 0, total: 1 },
        properties: { pascal: 0, camel: 0, snake: 0, other: 0, total: 0 },
        compliancePercentage: 100,
        classesNonPascal: [],
        propertiesNonCamel: [],
      },
    });
    expect(computeOverallSchemaQualityScore(m, null)).toBe(100);
  });
});

describe('computeOverallSchemaQualityDetail (#2548)', () => {
  it('matches overall score and includes letter grade', () => {
    const m = makeMinimalMetrics();
    const layout = {
      overallScore: 80,
      edgeCrossingCount: 0,
      nodeSpacingUniformityScore: 80,
      layoutSymmetryScore: 80,
      visualBalanceScore: 80,
    };
    const overall = computeOverallSchemaQualityScore(m, layout);
    const detail = computeOverallSchemaQualityDetail(m, layout);
    expect(detail.overall).toBe(overall);
    expect(detail.letterGrade).toMatch(/^[A-F]$/);
    expect(detail.layoutIncluded).toBe(true);
    expect(detail.rows).toHaveLength(4);
    expect(detail.rows.map((r) => r.id)).toEqual(['documentation', 'naming', 'structuralLoad', 'layout']);
  });

  it('omits layout row when layout is null and still matches overall', () => {
    const m = makeMinimalMetrics({
      complexityScore: 0,
      documentationCompletionPercentage: 100,
      namingCompliance: {
        classes: { pascal: 1, camel: 0, snake: 0, other: 0, total: 1 },
        properties: { pascal: 0, camel: 0, snake: 0, other: 0, total: 0 },
        compliancePercentage: 100,
        classesNonPascal: [],
        propertiesNonCamel: [],
      },
    });
    const overall = computeOverallSchemaQualityScore(m, null);
    const detail = computeOverallSchemaQualityDetail(m, null);
    expect(detail.overall).toBe(overall);
    expect(detail.layoutIncluded).toBe(false);
    expect(detail.rows).toHaveLength(3);
  });
});
