import { describe, it, expect } from '@jest/globals';
import {
  computeMaintainabilityIndexReport,
  computeTechnicalDebtMetricsReport,
  type SchemaMetricsResult,
} from '@/app/utils/schema-metrics';
import {
  formatScoreDelta,
  buildSchemaScoreCompareRows,
} from '@/app/utils/schema-version-score-compare';

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
    complexityBreakdown: [{ label: 'Class count', value: 3, weight: 10, contribution: 3 }],
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

describe('formatScoreDelta', () => {
  it('formats zero without sign', () => {
    expect(formatScoreDelta(0)).toBe('0');
  });

  it('formats positive integers with plus', () => {
    expect(formatScoreDelta(5)).toBe('+5');
  });

  it('formats negative integers', () => {
    expect(formatScoreDelta(-3)).toBe('-3');
  });
});

describe('buildSchemaScoreCompareRows', () => {
  it('labels complexity decrease as positive tone (simpler)', () => {
    const older = makeMinimalMetrics({ complexityScore: 60 });
    const newer = makeMinimalMetrics({ complexityScore: 40 });
    const rows = buildSchemaScoreCompareRows(older, newer);
    const row = rows.find((r) => r.label === 'Complexity score');
    expect(row?.delta).toBe('-20');
    expect(row?.deltaTone).toBe('positive');
  });

  it('labels documentation increase as positive tone', () => {
    const older = makeMinimalMetrics({ documentationCompletionPercentage: 50 });
    const newer = makeMinimalMetrics({ documentationCompletionPercentage: 75 });
    const rows = buildSchemaScoreCompareRows(older, newer);
    const row = rows.find((r) => r.label === 'Documentation');
    expect(row?.delta).toBe('+25');
    expect(row?.deltaTone).toBe('positive');
  });

  it('uses neutral tone for class count deltas', () => {
    const older = makeMinimalMetrics({ classCount: 2 });
    const newer = makeMinimalMetrics({ classCount: 5 });
    const rows = buildSchemaScoreCompareRows(older, newer);
    const row = rows.find((r) => r.label === 'Classes');
    expect(row?.delta).toBe('+3');
    expect(row?.deltaTone).toBe('neutral');
  });

  it('includes naming compliance row with percent values', () => {
    const a = makeMinimalMetrics({ namingCompliance: { ...makeMinimalMetrics().namingCompliance, compliancePercentage: 70 } });
    const b = makeMinimalMetrics({ namingCompliance: { ...makeMinimalMetrics().namingCompliance, compliancePercentage: 85 } });
    const rows = buildSchemaScoreCompareRows(a, b);
    const row = rows.find((r) => r.label === 'Naming compliance');
    expect(row?.valueA).toBe('70%');
    expect(row?.valueB).toBe('85%');
    expect(row?.delta).toBe('+15');
  });

  it('labels lower conditional cyclomatic as positive when newer has fewer (#612)', () => {
    const older = makeMinimalMetrics({ conditionalSchemaCyclomaticTotal: 5 });
    const newer = makeMinimalMetrics({ conditionalSchemaCyclomaticTotal: 2 });
    const rows = buildSchemaScoreCompareRows(older, newer);
    const row = rows.find((r) => r.label === 'Conditional schema cyclomatic');
    expect(row?.delta).toBe('-3');
    expect(row?.deltaTone).toBe('positive');
  });

  it('labels higher maintainability index as positive (#613)', () => {
    const older = makeMinimalMetrics({ maintainabilityIndex: { score: 40, scoreLabel: 'Medium', breakdown: [] } });
    const newer = makeMinimalMetrics({ maintainabilityIndex: { score: 55, scoreLabel: 'Medium', breakdown: [] } });
    const rows = buildSchemaScoreCompareRows(older, newer);
    const row = rows.find((r) => r.label === 'Maintainability index (#613)');
    expect(row?.delta).toBe('+15');
    expect(row?.deltaTone).toBe('positive');
  });

  it('labels lower technical debt as positive (#614)', () => {
    const older = makeMinimalMetrics({
      technicalDebtMetrics: { debtScore: 72, scoreLabel: 'High', breakdown: [] },
    });
    const newer = makeMinimalMetrics({
      technicalDebtMetrics: { debtScore: 48, scoreLabel: 'Medium', breakdown: [] },
    });
    const rows = buildSchemaScoreCompareRows(older, newer);
    const row = rows.find((r) => r.label === 'Technical debt (#614)');
    expect(row?.delta).toBe('-24');
    expect(row?.deltaTone).toBe('positive');
  });
});
