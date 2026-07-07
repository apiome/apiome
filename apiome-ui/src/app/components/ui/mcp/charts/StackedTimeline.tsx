'use client';

import * as React from 'react';
import { cn } from '../../../../../../lib/utils';
import { ChartFrame } from './ChartFrame';
import {
  chartCategoricalTone,
  chartSeriesStyle,
  type ChartSeriesTone,
  CHART_SURFACE,
} from './chartTokens';
import { clamp, sumValues } from './chartGeometry';

/** A named series (a band in the stack) with a stable key and optional pinned tone. */
export interface StackSeries {
  key: string;
  label?: string;
  tone?: ChartSeriesTone;
}

/** One period (a column): its label plus a value per series key. */
export interface StackPeriod {
  label: string;
  values: Record<string, number>;
}

const H = 100;
const GAP = 4;

export interface StackedTimelineProps {
  /** The stacked series (bottom→top of each column), in draw order. */
  series: readonly StackSeries[];
  /** The periods (columns), left→right. */
  periods: readonly StackPeriod[];
  /** Fixed column-total maximum; when omitted the tallest column total defines the scale. */
  domainMax?: number;
  /** Accessible name; defaults to a generated summary. */
  title?: string;
  /** Extra classes for the wrapping figure (set height here). */
  className?: string;
}

/**
 * `<StackedTimeline>` — a stacked bar chart over an ordered axis (per-version churn split by
 * added/changed/removed, tool invocations by outcome over time). Each column stacks its series
 * bottom→top; columns scale to the largest column total unless `domainMax` is pinned. Series take an
 * explicit `tone` or a stable categorical color. Empty input renders the shared empty state.
 * Responsive via `viewBox`; SSR-safe.
 */
export function StackedTimeline({
  series,
  periods,
  domainMax,
  title,
  className,
}: StackedTimelineProps) {
  const isEmpty = periods.length === 0 || series.length === 0;

  const columnTotal = (p: StackPeriod) => sumValues(series.map((s) => p.values[s.key] ?? 0));
  const max = domainMax && domainMax > 0 ? domainMax : Math.max(1, ...periods.map(columnTotal));

  const n = Math.max(1, periods.length);
  const bandW = (100 - GAP * (n + 1)) / n;

  const summary =
    periods
      .map((p) => `${p.label}: ${columnTotal(p)}`)
      .join(', ') || 'No data';
  const label = title ?? `Stacked timeline — ${summary}`;

  return (
    <ChartFrame
      title={label}
      description={summary}
      viewBox={`0 0 100 ${H}`}
      preserveAspectRatio="none"
      isEmpty={isEmpty}
      className={cn('h-40 w-full', className)}
      tableFallback={
        <table>
          <caption>{label}</caption>
          <thead>
            <tr>
              <th scope="col">Period</th>
              {series.map((s) => (
                <th key={s.key} scope="col">
                  {s.label ?? s.key}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {periods.map((p, i) => (
              <tr key={i}>
                <th scope="row">{p.label}</th>
                {series.map((s) => (
                  <td key={s.key}>{p.values[s.key] ?? 0}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      }
    >
      {periods.map((p, pi) => {
        const x = GAP + pi * (bandW + GAP);
        // Walk series bottom→top, accumulating height so bands sit on top of one another.
        let acc = 0;
        return (
          <g key={pi}>
            {series.map((s, si) => {
              const raw = p.values[s.key] ?? 0;
              const h = H * (clamp(Number.isFinite(raw) ? raw : 0, 0, max) / max);
              const y = H - acc - h;
              acc += h;
              const style = chartSeriesStyle(s.tone ?? chartCategoricalTone(si));
              if (h <= 0) return null;
              return (
                <rect key={s.key} x={x} y={y} width={bandW} height={h} className={style.fillClass}>
                  <title>{`${p.label} — ${s.label ?? s.key}: ${raw}`}</title>
                </rect>
              );
            })}
          </g>
        );
      })}
      <line
        x1={0}
        y1={H}
        x2={100}
        y2={H}
        strokeWidth={0.5}
        vectorEffect="non-scaling-stroke"
        className={CHART_SURFACE.trackStrokeClass}
      />
    </ChartFrame>
  );
}
