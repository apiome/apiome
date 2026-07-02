import { describe, it, expect } from '@jest/globals';
import { computeTechnicalDebtMetricsReport } from '@/app/utils/schema-metrics';

describe('computeTechnicalDebtMetricsReport (#614)', () => {
  it('returns 0–100 debtScore and Low label for an empty-style healthy snapshot', () => {
    const r = computeTechnicalDebtMetricsReport({
      documentationCompletionPercentage: 100,
      namingCompliancePercentage: 100,
      complexityScore: 0,
      dependencyGraphScore: 0,
      conditionalSchemaCyclomaticTotal: 0,
      circularDependencyCount: 0,
      deepestChainLength: 0,
      classCount: 1,
      isolatedClassCount: 0,
      cognitiveComplexityPerClass: [{ classId: 'a', className: 'A', score: 0, propertyContribution: 0, referenceContribution: 0, conditionalSchemaCyclomaticContribution: 0 }],
      averagePropertiesPerClass: 3,
    });
    expect(r.debtScore).toBeGreaterThanOrEqual(0);
    expect(r.debtScore).toBeLessThanOrEqual(100);
    expect(r.scoreLabel).toBe('Low');
    expect(r.breakdown.length).toBe(10);
  });

  it('increases debt when documentation, naming, and complexity worsen', () => {
    const good = computeTechnicalDebtMetricsReport({
      documentationCompletionPercentage: 100,
      namingCompliancePercentage: 100,
      complexityScore: 10,
      dependencyGraphScore: 5,
      conditionalSchemaCyclomaticTotal: 0,
      circularDependencyCount: 0,
      deepestChainLength: 1,
      classCount: 2,
      isolatedClassCount: 0,
      cognitiveComplexityPerClass: [
        { classId: 'a', className: 'A', score: 2, propertyContribution: 2, referenceContribution: 0, conditionalSchemaCyclomaticContribution: 0 },
        { classId: 'b', className: 'B', score: 2, propertyContribution: 2, referenceContribution: 0, conditionalSchemaCyclomaticContribution: 0 },
      ],
      averagePropertiesPerClass: 4,
    });
    const bad = computeTechnicalDebtMetricsReport({
      documentationCompletionPercentage: 40,
      namingCompliancePercentage: 50,
      complexityScore: 85,
      dependencyGraphScore: 80,
      conditionalSchemaCyclomaticTotal: 12,
      circularDependencyCount: 3,
      deepestChainLength: 8,
      classCount: 2,
      isolatedClassCount: 1,
      cognitiveComplexityPerClass: [
        { classId: 'a', className: 'A', score: 40, propertyContribution: 20, referenceContribution: 20, conditionalSchemaCyclomaticContribution: 0 },
        { classId: 'b', className: 'B', score: 40, propertyContribution: 20, referenceContribution: 20, conditionalSchemaCyclomaticContribution: 0 },
      ],
      averagePropertiesPerClass: 22,
    });
    expect(bad.debtScore).toBeGreaterThan(good.debtScore);
    expect(bad.scoreLabel).toBe('High');
  });
});
