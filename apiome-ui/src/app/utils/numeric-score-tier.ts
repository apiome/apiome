/**
 * Shared 0–100 score bands where higher is better (#248).
 *
 * - 90–100: Excellent — Production ready (green)
 * - 70–89: Good — Minor improvements needed (yellow)
 * - 50–69: Fair — Significant improvements recommended (orange)
 * - 0–49: Poor — Major issues must be addressed (red)
 */

export type NumericScoreBand = 'excellent' | 'good' | 'fair' | 'poor';

export interface NumericScoreTierStyle {
  band: NumericScoreBand;
  rangeLabel: string;
  shortLabel: string;
  detailLabel: string;
  textClass: string;
  /** For SVG gauges using `stroke-current` */
  gaugeStrokeClass: string;
  progressGradientClass: string;
  barSolidClass: string;
}

function tier(
  band: NumericScoreBand,
  rangeLabel: string,
  shortLabel: string,
  detailLabel: string,
  textClass: string,
  gaugeStrokeClass: string,
  progressGradientClass: string,
  barSolidClass: string
): NumericScoreTierStyle {
  return {
    band,
    rangeLabel,
    shortLabel,
    detailLabel,
    textClass,
    gaugeStrokeClass,
    progressGradientClass,
    barSolidClass,
  };
}

const EXCELLENT = tier(
  'excellent',
  '90–100',
  'Excellent',
  'Production ready',
  'text-green-600 dark:text-green-400',
  'text-green-500 dark:text-green-400',
  'from-green-500 to-green-600',
  'bg-green-500'
);

const GOOD = tier(
  'good',
  '70–89',
  'Good',
  'Minor improvements needed',
  'text-yellow-600 dark:text-yellow-400',
  'text-yellow-500 dark:text-yellow-400',
  'from-yellow-500 to-amber-500',
  'bg-yellow-500'
);

const FAIR = tier(
  'fair',
  '50–69',
  'Fair',
  'Significant improvements recommended',
  'text-orange-600 dark:text-orange-400',
  'text-orange-500 dark:text-orange-400',
  'from-orange-500 to-orange-600',
  'bg-orange-500'
);

const POOR = tier(
  'poor',
  '0–49',
  'Poor',
  'Major issues must be addressed',
  'text-red-600 dark:text-red-400',
  'text-red-500 dark:text-red-400',
  'from-red-500 to-red-600',
  'bg-red-500'
);

/** Static legend rows for tooltips and help copy */
export const NUMERIC_SCORE_TIER_LEGEND: readonly NumericScoreTierStyle[] = [
  EXCELLENT,
  GOOD,
  FAIR,
  POOR,
] as const;

/**
 * @param percent Raw 0–100 score (fractional values rounded to nearest integer)
 */
export function getNumericScoreTier(percent: number): NumericScoreTierStyle {
  const n = Math.min(100, Math.max(0, Math.round(Number(percent))));
  if (n >= 90) return EXCELLENT;
  if (n >= 70) return GOOD;
  if (n >= 50) return FAIR;
  return POOR;
}

/**
 * Letter grade aligned to the same numeric bands as {@link getNumericScoreTier},
 * with D/F split in the poor band so the union stays A–F for legacy fields.
 */
export function letterGradeFromOverallPercent(percent: number): 'A' | 'B' | 'C' | 'D' | 'F' {
  const n = Math.min(100, Math.max(0, Math.round(Number(percent))));
  if (n >= 90) return 'A';
  if (n >= 70) return 'B';
  if (n >= 50) return 'C';
  if (n >= 40) return 'D';
  return 'F';
}
