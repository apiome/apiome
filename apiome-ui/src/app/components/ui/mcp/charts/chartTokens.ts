/**
 * Token-driven SVG chart kit — palette & series-tone mapping (V2-MCP-28.3 / MCAT-14.3).
 *
 * The chart kit follows the same design principle as {@link GradeGlyph} and the rest of the MCP UI
 * primitives: **consumers pass domain values, primitives pick the color**. This module holds the
 * *pure*, React-free mapping from a semantic "series tone" (or a stable series index) to the
 * Tailwind utility classes each SVG mark paints with. Because chart marks are SVG, colors are
 * expressed as `fill-*` / `stroke-*` / `text-*` utilities (the project's token layer, mapped with
 * `dark:` variants in `globals.css`) — never a hex or `rgb()` literal in a consumer.
 *
 * Keeping this logic here (and free of JSX) lets it be unit-tested directly and keeps the chart
 * components free of color/branching literals — mirroring `mcpUiPrimitives.ts`.
 */

/**
 * The semantic categorical tones a chart series can take. This mirrors the {@link McpBadgeTone}
 * language so a chart and the badges beside it read as one palette. `neutral` is the muted
 * gray used for baselines, gridlines, and "other" buckets.
 */
export type ChartSeriesTone =
  | 'indigo'
  | 'emerald'
  | 'amber'
  | 'red'
  | 'blue'
  | 'violet'
  | 'green'
  | 'orange'
  | 'cyan'
  | 'pink'
  | 'neutral';

/** The Tailwind classes one series paints its marks with, split by SVG paint channel. */
export interface ChartSeriesStyle {
  /** The tone this style resolves. */
  tone: ChartSeriesTone;
  /** `fill-*` class for filled marks (bars, donut/heatmap cells, radar/area fills). */
  fillClass: string;
  /** `stroke-*` class for stroked marks (sparkline/line paths, radar outline). */
  strokeClass: string;
  /** `text-*` class so a mark can use `fill="currentColor"` / `stroke="currentColor"` and inherit. */
  textClass: string;
}

/**
 * The tone → class table. Each tone maps to the 500 ramp in light and the 400 ramp in dark, matching
 * the intensity the grade glyph and badges already use so the charts sit in the same palette.
 */
const CHART_SERIES_STYLES: Record<ChartSeriesTone, ChartSeriesStyle> = {
  indigo: {
    tone: 'indigo',
    fillClass: 'fill-indigo-500 dark:fill-indigo-400',
    strokeClass: 'stroke-indigo-500 dark:stroke-indigo-400',
    textClass: 'text-indigo-500 dark:text-indigo-400',
  },
  emerald: {
    tone: 'emerald',
    fillClass: 'fill-emerald-500 dark:fill-emerald-400',
    strokeClass: 'stroke-emerald-500 dark:stroke-emerald-400',
    textClass: 'text-emerald-500 dark:text-emerald-400',
  },
  amber: {
    tone: 'amber',
    fillClass: 'fill-amber-500 dark:fill-amber-400',
    strokeClass: 'stroke-amber-500 dark:stroke-amber-400',
    textClass: 'text-amber-500 dark:text-amber-400',
  },
  red: {
    tone: 'red',
    fillClass: 'fill-red-500 dark:fill-red-400',
    strokeClass: 'stroke-red-500 dark:stroke-red-400',
    textClass: 'text-red-500 dark:text-red-400',
  },
  blue: {
    tone: 'blue',
    fillClass: 'fill-blue-500 dark:fill-blue-400',
    strokeClass: 'stroke-blue-500 dark:stroke-blue-400',
    textClass: 'text-blue-500 dark:text-blue-400',
  },
  violet: {
    tone: 'violet',
    fillClass: 'fill-violet-500 dark:fill-violet-400',
    strokeClass: 'stroke-violet-500 dark:stroke-violet-400',
    textClass: 'text-violet-500 dark:text-violet-400',
  },
  green: {
    tone: 'green',
    fillClass: 'fill-green-500 dark:fill-green-400',
    strokeClass: 'stroke-green-500 dark:stroke-green-400',
    textClass: 'text-green-500 dark:text-green-400',
  },
  orange: {
    tone: 'orange',
    fillClass: 'fill-orange-500 dark:fill-orange-400',
    strokeClass: 'stroke-orange-500 dark:stroke-orange-400',
    textClass: 'text-orange-500 dark:text-orange-400',
  },
  cyan: {
    tone: 'cyan',
    fillClass: 'fill-cyan-500 dark:fill-cyan-400',
    strokeClass: 'stroke-cyan-500 dark:stroke-cyan-400',
    textClass: 'text-cyan-500 dark:text-cyan-400',
  },
  pink: {
    tone: 'pink',
    fillClass: 'fill-pink-500 dark:fill-pink-400',
    strokeClass: 'stroke-pink-500 dark:stroke-pink-400',
    textClass: 'text-pink-500 dark:text-pink-400',
  },
  neutral: {
    tone: 'neutral',
    fillClass: 'fill-slate-300 dark:fill-slate-600',
    strokeClass: 'stroke-slate-300 dark:stroke-slate-600',
    textClass: 'text-slate-400 dark:text-slate-500',
  },
};

/**
 * The order tones are handed out to a categorical series (donut segments, stacked bands, multi-line
 * charts) when the consumer does not pin a tone. Chosen so adjacent series are easy to tell apart.
 * `neutral` is intentionally excluded — it is reserved for baselines/"other", not auto-assignment.
 */
export const CHART_CATEGORICAL_ORDER: readonly ChartSeriesTone[] = [
  'indigo',
  'emerald',
  'amber',
  'violet',
  'blue',
  'orange',
  'cyan',
  'pink',
  'red',
  'green',
];

/** Resolve the {@link ChartSeriesStyle} for a tone (defaults to `neutral` for an unknown value). */
export function chartSeriesStyle(tone: ChartSeriesTone | null | undefined): ChartSeriesStyle {
  return (tone && CHART_SERIES_STYLES[tone]) || CHART_SERIES_STYLES.neutral;
}

/**
 * Resolve the tone for the `index`-th series in a categorical chart, cycling through
 * {@link CHART_CATEGORICAL_ORDER} so any number of series get a stable, repeatable color. A negative
 * index collapses to the first tone.
 */
export function chartCategoricalTone(index: number): ChartSeriesTone {
  const n = CHART_CATEGORICAL_ORDER.length;
  const safe = Number.isFinite(index) ? Math.trunc(index) : 0;
  return CHART_CATEGORICAL_ORDER[((safe % n) + n) % n];
}

/** Convenience: the resolved style for the `index`-th categorical series. */
export function chartCategoricalStyle(index: number): ChartSeriesStyle {
  return chartSeriesStyle(chartCategoricalTone(index));
}

/**
 * Shared surface classes used by every chart for non-data furniture, so the palette lives in one
 * place: the muted track/gridline color and the axis/label text color. These are `stroke`/`text`
 * utilities applied to SVG elements.
 */
export const CHART_SURFACE = {
  /** Gridlines, unfilled tracks (donut/gauge base ring, bar track). */
  trackStrokeClass: 'stroke-gray-200 dark:stroke-gray-700',
  /** Filled track background (e.g. heatmap empty cell, radar web fill). */
  trackFillClass: 'fill-gray-100 dark:fill-gray-800',
  /** Axis / tick / value label text. */
  labelClass: 'fill-gray-500 dark:fill-gray-400',
  /** Stronger label text for emphasized values. */
  labelStrongClass: 'fill-gray-700 dark:fill-gray-200',
} as const;
