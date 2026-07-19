/**
 * Analytics states and accessible chart summaries (UXE-1.3).
 *
 * §28.4 requires every chart to offer "table view, accessible summary,
 * drill-down and CSV/API export", and to apply privacy thresholds to
 * low-volume data. Both are properties of the *data*, not of the drawing, so
 * they are decided here and every chart inherits them.
 *
 * A chart that cannot be read as text is not accessible, so the summary and the
 * table rows are produced from the same series the chart draws — they cannot
 * drift from what is plotted.
 */

import type { AuthoringTone } from './tokens';

/**
 * State of an analytics panel.
 *
 * `threshold` is deliberately distinct from `empty`: "we have no data" and "we
 * have data but too little to show without identifying someone" are different
 * facts, and conflating them would either leak or mislead.
 */
export type AuthoringAnalyticsState = 'loading' | 'ready' | 'empty' | 'threshold' | 'error';

/** One point in a series. */
export type AuthoringAnalyticsPoint = {
  /** Bucket label, e.g. an ISO date or a route. */
  label: string;
  value: number;
  /** Comparison-period value, when a comparison is active. */
  comparisonValue?: number;
};

/** One measured series. */
export type AuthoringAnalyticsSeries = {
  id: string;
  label: string;
  /** Unit for formatting, e.g. `requests`, `ms`, `%`. */
  unit: string;
  points: readonly AuthoringAnalyticsPoint[];
};

/** Default minimum observations before a series may be shown. */
export const AUTHORING_PRIVACY_THRESHOLD = 10;

/** Aggregate view of a series, usable as the chart's accessible summary. */
export type AuthoringSeriesSummary = {
  total: number;
  min: number;
  max: number;
  /** Mean, rounded to one decimal. */
  average: number;
  /** First-to-last change as a percentage, or `undefined` when undefined. */
  changePercent?: number;
  /** Direction of travel, for a text cue alongside any colour. */
  direction: 'up' | 'down' | 'flat';
  tone: AuthoringTone;
  /** Sentence describing the series without reference to the drawing. */
  description: string;
};

/**
 * Summarise a series as text.
 *
 * The description names the range, the peak and the direction, which is what a
 * sighted reader takes from the shape of the line. Direction is reported as a
 * word as well as a tone, so the trend survives greyscale (§27.4).
 *
 * @param series - Series to summarise.
 * @returns Statistics and the sentence to announce.
 */
export function summarizeAuthoringSeries(series: AuthoringAnalyticsSeries): AuthoringSeriesSummary {
  const values = series.points.map((point) => point.value);

  if (values.length === 0) {
    return {
      total: 0,
      min: 0,
      max: 0,
      average: 0,
      direction: 'flat',
      tone: 'neutral',
      description: `${series.label}: no data in this period.`,
    };
  }

  const total = values.reduce((sum, value) => sum + value, 0);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const average = Math.round((total / values.length) * 10) / 10;

  const first = values[0];
  const last = values[values.length - 1];
  // A change from zero has no meaningful percentage, so it is reported as a
  // direction only rather than as an infinite increase.
  const changePercent =
    first === 0 ? undefined : Math.round(((last - first) / Math.abs(first)) * 100);

  const direction: AuthoringSeriesSummary['direction'] =
    last > first ? 'up' : last < first ? 'down' : 'flat';

  const peak = series.points.find((point) => point.value === max)!;
  const changeText =
    direction === 'flat'
      ? 'unchanged over the period'
      : `${direction === 'up' ? 'up' : 'down'} over the period${
          changePercent === undefined ? '' : ` by ${Math.abs(changePercent)}%`
        }`;

  return {
    total,
    min,
    max,
    average,
    changePercent,
    direction,
    tone: 'info',
    description:
      `${series.label}: ${formatAuthoringMetric(total, series.unit)} total across ` +
      `${values.length} ${values.length === 1 ? 'bucket' : 'buckets'}, ` +
      `averaging ${formatAuthoringMetric(average, series.unit)}, ` +
      `peaking at ${formatAuthoringMetric(max, series.unit)} on ${peak.label}, ${changeText}.`,
  };
}

/**
 * Decide which state an analytics panel should render.
 *
 * Threshold suppression is applied to the *total*, not to individual buckets:
 * a series whose buckets each fall below the threshold but which sums above it
 * is safe to show, and suppressing it would hide legitimate data.
 *
 * @param series - Series to render, if any.
 * @param options - Loading and error signals, and the threshold to apply.
 * @returns The state the panel should show.
 */
export function resolveAuthoringAnalyticsState(
  series: AuthoringAnalyticsSeries | undefined,
  options: {
    loading?: boolean;
    error?: boolean;
    threshold?: number;
  } = {}
): AuthoringAnalyticsState {
  if (options.error) return 'error';
  if (options.loading) return 'loading';
  if (!series || series.points.length === 0) return 'empty';

  const threshold = options.threshold ?? AUTHORING_PRIVACY_THRESHOLD;
  const total = series.points.reduce((sum, point) => sum + point.value, 0);
  return total < threshold ? 'threshold' : 'ready';
}

/** How each analytics state is explained to the viewer. */
const STATE_COPY: Record<AuthoringAnalyticsState, { title: string; description: string }> = {
  loading: {
    title: 'Loading',
    description: 'Fetching measurements for this period.',
  },
  ready: {
    title: 'Ready',
    description: 'Measurements for this period.',
  },
  empty: {
    title: 'No data yet',
    description:
      'Nothing was measured in this period. Publish a release or widen the time range to see activity.',
  },
  threshold: {
    title: 'Below the privacy threshold',
    description:
      'Too few events were recorded to show without risking identification. Widen the time range.',
  },
  error: {
    title: 'Could not load',
    description: 'The measurements could not be fetched. Retry, or open the logs for detail.',
  },
};

/**
 * Explain an analytics state.
 *
 * @param state - Panel state.
 * @returns Title and explanatory sentence.
 */
export function describeAuthoringAnalyticsState(state: AuthoringAnalyticsState) {
  return STATE_COPY[state];
}

/**
 * Format a metric with its unit.
 *
 * Percentages and durations read wrong with a leading space, so they are
 * suffixed directly; counted units keep the space.
 *
 * @param value - Numeric value.
 * @param unit - Unit label.
 * @returns e.g. `1,240 requests`, `98%`, `312ms`.
 */
export function formatAuthoringMetric(value: number, unit: string): string {
  const formatted = value.toLocaleString('en-US');
  if (unit === '%' || unit === 'ms' || unit === 's') return `${formatted}${unit}`;
  return `${formatted} ${unit}`;
}
