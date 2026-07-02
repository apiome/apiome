import { describe, it, expect } from '@jest/globals';
import {
  computeMaintainabilityIndexReport,
  computeSchemaMetricsFromClasses,
} from '@/app/utils/schema-metrics';

describe('maintainability index (#613)', () => {
  it('scores 0–100 with High label when docs, naming, and simplicity are strong', () => {
    const r = computeMaintainabilityIndexReport({
      documentationCompletionPercentage: 100,
      namingCompliancePercentage: 100,
      complexityScore: 0,
      dependencyGraphScore: 0,
      cognitiveComplexityPerClass: [],
      averagePropertiesPerClass: 3,
      classCount: 2,
    });
    expect(r.score).toBe(100);
    expect(r.scoreLabel).toBe('High');
    expect(r.breakdown.some((b) => b.label === 'Documentation')).toBe(true);
  });

  it('applies cognitive and class-size penalties when drivers are poor', () => {
    const r = computeMaintainabilityIndexReport({
      documentationCompletionPercentage: 0,
      namingCompliancePercentage: 0,
      complexityScore: 100,
      dependencyGraphScore: 100,
      cognitiveComplexityPerClass: [
        {
          classId: 'a',
          className: 'A',
          score: 40,
          propertyContribution: 20,
          referenceContribution: 20,
          conditionalSchemaCyclomaticContribution: 0,
        },
      ],
      averagePropertiesPerClass: 30,
      classCount: 1,
    });
    expect(r.score).toBeGreaterThanOrEqual(0);
    expect(r.score).toBeLessThanOrEqual(100);
    expect(r.scoreLabel).toBe('Low');
    expect(r.breakdown.some((b) => b.label.includes('Cognitive load penalty'))).toBe(true);
    expect(r.breakdown.some((b) => b.label.includes('Class size penalty'))).toBe(true);
  });

  it('is present on computeSchemaMetricsFromClasses output', () => {
    const classes = [{ id: 'a', name: 'User', properties: [], schema: {} }];
    const m = computeSchemaMetricsFromClasses(classes);
    expect(m.maintainabilityIndex.score).toBeGreaterThanOrEqual(0);
    expect(m.maintainabilityIndex.score).toBeLessThanOrEqual(100);
    expect(['Low', 'Medium', 'High']).toContain(m.maintainabilityIndex.scoreLabel);
  });
});
