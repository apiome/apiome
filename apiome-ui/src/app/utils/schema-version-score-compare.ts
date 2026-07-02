/**
 * Side-by-side schema score comparison between two versions (#251).
 */

import type { SchemaMetricsResult } from './schema-metrics';

export type ScoreCompareDeltaTone = 'positive' | 'negative' | 'neutral';

export interface SchemaScoreCompareRow {
  label: string;
  valueA: string;
  valueB: string;
  delta: string;
  deltaTone: ScoreCompareDeltaTone;
}

function fmtInt(n: number): string {
  return String(Math.round(n));
}

function fmtPct(n: number): string {
  return `${Math.round(n)}%`;
}

export function formatScoreDelta(value: number, decimals: 0 | 1 = 0): string {
  if (value === 0) return '0';
  const rounded = decimals === 0 ? Math.round(value) : Number(value.toFixed(1));
  const sign = rounded > 0 ? '+' : '';
  return `${sign}${rounded}`;
}

function toneLowerIsBetter(delta: number): ScoreCompareDeltaTone {
  if (delta === 0) return 'neutral';
  return delta < 0 ? 'positive' : 'negative';
}

function toneHigherIsBetter(delta: number): ScoreCompareDeltaTone {
  if (delta === 0) return 'neutral';
  return delta > 0 ? 'positive' : 'negative';
}

export function buildSchemaScoreCompareRows(
  a: SchemaMetricsResult,
  b: SchemaMetricsResult
): SchemaScoreCompareRow[] {
  const rows: SchemaScoreCompareRow[] = [];

  const push = (
    label: string,
    valA: number,
    valB: number,
    format: (n: number) => string,
    toneFn: (delta: number) => ScoreCompareDeltaTone,
    decimals: 0 | 1 = 0
  ) => {
    const delta = valB - valA;
    rows.push({
      label,
      valueA: format(valA),
      valueB: format(valB),
      delta: formatScoreDelta(delta, decimals),
      deltaTone: toneFn(delta),
    });
  };

  push('Complexity score', a.complexityScore, b.complexityScore, fmtInt, toneLowerIsBetter);
  push(
    'Documentation',
    a.documentationCompletionPercentage,
    b.documentationCompletionPercentage,
    fmtPct,
    toneHigherIsBetter
  );
  push(
    'Naming compliance',
    a.namingCompliance.compliancePercentage,
    b.namingCompliance.compliancePercentage,
    fmtPct,
    toneHigherIsBetter
  );
  push('Classes', a.classCount, b.classCount, fmtInt, () => 'neutral');
  push('Relationships', a.relationshipCount, b.relationshipCount, fmtInt, () => 'neutral');
  push('Properties', a.totalProperties, b.totalProperties, fmtInt, () => 'neutral');
  push(
    'Conditional schema cyclomatic',
    a.conditionalSchemaCyclomaticTotal,
    b.conditionalSchemaCyclomaticTotal,
    fmtInt,
    toneLowerIsBetter
  );
  push(
    'Maintainability index (#613)',
    a.maintainabilityIndex.score,
    b.maintainabilityIndex.score,
    fmtInt,
    toneHigherIsBetter
  );
  push(
    'Technical debt (#614)',
    a.technicalDebtMetrics.debtScore,
    b.technicalDebtMetrics.debtScore,
    fmtInt,
    toneLowerIsBetter
  );

  return rows;
}
