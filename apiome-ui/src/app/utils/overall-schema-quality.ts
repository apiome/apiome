/**
 * Single 0–100 overall schema quality score for Studio (#245).
 * Combines documentation, naming, inverted complexity (lower structural load is better),
 * and canvas layout quality using fixed weights that sum to 100%.
 */

import type { LayoutQualityResult } from '@/app/utils/layout-quality';
import type { SchemaMetricsResult } from '@/app/utils/schema-metrics';
import { getNumericScoreTier, letterGradeFromOverallPercent } from '@/app/utils/numeric-score-tier';

const W_DOC = 0.3;
const W_NAMING = 0.3;
const W_SIMPLICITY = 0.25;
const W_LAYOUT = 0.15;

/** Human-readable weight labels for UI (must match {@link computeOverallSchemaQualityScore}). */
export const OVERALL_SCHEMA_QUALITY_WEIGHTS = {
  documentation: '30%',
  naming: '30%',
  structuralLoad: '25%',
  layout: '15%',
} as const;

export interface OverallSchemaQualityBreakdownRow {
  id: 'documentation' | 'naming' | 'structuralLoad' | 'layout';
  label: string;
  /** Raw 0–100 input to the weighted blend (structural load uses inverted complexity). */
  value: number;
  /** Effective weight as a fraction of 1 (after renormalization when layout is omitted). */
  effectiveWeight: number;
  /** contribution = effectiveWeight * value (before final rounding). */
  contribution: number;
}

export interface OverallSchemaQualityDetail {
  overall: number;
  letterGrade: ReturnType<typeof letterGradeFromOverallPercent>;
  tier: ReturnType<typeof getNumericScoreTier>;
  layoutIncluded: boolean;
  rows: OverallSchemaQualityBreakdownRow[];
}

/**
 * Explains how the overall score is built from metrics; matches {@link computeOverallSchemaQualityScore}.
 */
export function computeOverallSchemaQualityDetail(
  metrics: SchemaMetricsResult,
  layoutQuality: LayoutQualityResult | null | undefined
): OverallSchemaQualityDetail {
  const doc = metrics.documentationCompletionPercentage;
  const naming = metrics.namingCompliance.compliancePercentage;
  const simplicity = 100 - metrics.complexityScore;
  const overall = computeOverallSchemaQualityScore(metrics, layoutQuality);
  const tier = getNumericScoreTier(overall);
  const letterGrade = letterGradeFromOverallPercent(overall);

  if (layoutQuality == null) {
    const sumW = W_DOC + W_NAMING + W_SIMPLICITY;
    const wDoc = W_DOC / sumW;
    const wNam = W_NAMING / sumW;
    const wSim = W_SIMPLICITY / sumW;
    const rows: OverallSchemaQualityBreakdownRow[] = [
      {
        id: 'documentation',
        label: 'Documentation coverage',
        value: doc,
        effectiveWeight: wDoc,
        contribution: wDoc * doc,
      },
      {
        id: 'naming',
        label: 'Naming conventions',
        value: naming,
        effectiveWeight: wNam,
        contribution: wNam * naming,
      },
      {
        id: 'structuralLoad',
        label: 'Structural load (100 − complexity)',
        value: simplicity,
        effectiveWeight: wSim,
        contribution: wSim * simplicity,
      },
    ];
    return { overall, letterGrade, tier, layoutIncluded: false, rows };
  }

  const rows: OverallSchemaQualityBreakdownRow[] = [
    {
      id: 'documentation',
      label: 'Documentation coverage',
      value: doc,
      effectiveWeight: W_DOC,
      contribution: W_DOC * doc,
    },
    {
      id: 'naming',
      label: 'Naming conventions',
      value: naming,
      effectiveWeight: W_NAMING,
      contribution: W_NAMING * naming,
    },
    {
      id: 'structuralLoad',
      label: 'Structural load (100 − complexity)',
      value: simplicity,
      effectiveWeight: W_SIMPLICITY,
      contribution: W_SIMPLICITY * simplicity,
    },
    {
      id: 'layout',
      label: 'Canvas layout quality',
      value: layoutQuality.overallScore,
      effectiveWeight: W_LAYOUT,
      contribution: W_LAYOUT * layoutQuality.overallScore,
    },
  ];
  return { overall, letterGrade, tier, layoutIncluded: true, rows };
}

/**
 * Weighted composite of schema metrics and optional layout quality.
 * When `layoutQuality` is omitted, layout is excluded and weights are renormalized across the other three factors.
 */
export function computeOverallSchemaQualityScore(
  metrics: SchemaMetricsResult,
  layoutQuality: LayoutQualityResult | null | undefined
): number {
  const doc = metrics.documentationCompletionPercentage;
  const naming = metrics.namingCompliance.compliancePercentage;
  const simplicity = 100 - metrics.complexityScore;

  if (layoutQuality == null) {
    const sumW = W_DOC + W_NAMING + W_SIMPLICITY;
    const raw = ((W_DOC / sumW) * doc + (W_NAMING / sumW) * naming + (W_SIMPLICITY / sumW) * simplicity);
    return Math.min(100, Math.max(0, Math.round(raw)));
  }

  const raw =
    W_DOC * doc + W_NAMING * naming + W_SIMPLICITY * simplicity + W_LAYOUT * layoutQuality.overallScore;
  return Math.min(100, Math.max(0, Math.round(raw)));
}
