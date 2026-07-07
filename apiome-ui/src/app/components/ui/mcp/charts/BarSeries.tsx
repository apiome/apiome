'use client';

import * as React from 'react';
import { cn } from '../../../../../../lib/utils';
import { ChartFrame } from './ChartFrame';
import { chartSeriesStyle, type ChartSeriesTone, CHART_SURFACE } from './chartTokens';
import { clamp, maxValue } from './chartGeometry';

/** One labelled bar. `tone` overrides the series default for a single bar (e.g. to flag an outlier). */
export interface BarDatum {
  label: string;
  value: number;
  tone?: ChartSeriesTone;
}

const H = 100;
const GAP = 6;

export interface BarSeriesProps {
  /** The bars, drawn left→right. */
  data: readonly BarDatum[];
  /** Default color for bars without their own `tone`; defaults to `indigo`. */
  tone?: ChartSeriesTone;
  /** Fixed value maximum; when omitted the tallest bar defines the scale. */
  domainMax?: number;
  /** Accessible name; defaults to a generated summary. */
  title?: string;
  /** Extra classes for the wrapping figure (set height here). */
  className?: string;
}

/**
 * `<BarSeries>` — a simple vertical bar chart for small categorical comparisons (capability counts
 * by type, findings by severity). Each bar scales to the series max (or a pinned `domainMax`), and a
 * bar can override the series color via its own `tone`. Empty data renders the shared empty state.
 * Responsive via `viewBox`; SSR-safe.
 */
export function BarSeries({ data, tone = 'indigo', domainMax, title, className }: BarSeriesProps) {
  const isEmpty = data.length === 0;
  const max = domainMax && domainMax > 0 ? domainMax : maxValue(data.map((d) => d.value)) || 1;
  const n = Math.max(1, data.length);
  const bandW = (100 - GAP * (n + 1)) / n;

  const summary = data.map((d) => `${d.label}: ${d.value}`).join(', ') || 'No data';
  const label = title ?? `Bar chart — ${summary}`;

  return (
    <ChartFrame
      title={label}
      description={summary}
      viewBox={`0 0 100 ${H}`}
      preserveAspectRatio="none"
      isEmpty={isEmpty}
      className={cn('h-32 w-full', className)}
      tableFallback={
        <table>
          <caption>{label}</caption>
          <tbody>
            {data.map((d, i) => (
              <tr key={i}>
                <th scope="row">{d.label}</th>
                <td>{d.value}</td>
              </tr>
            ))}
          </tbody>
        </table>
      }
    >
      {data.map((d, i) => {
        const style = chartSeriesStyle(d.tone ?? tone);
        const h = H * (clamp(Number.isFinite(d.value) ? d.value : 0, 0, max) / max);
        const x = GAP + i * (bandW + GAP);
        const y = H - h;
        return (
          <rect
            key={i}
            x={x}
            y={y}
            width={bandW}
            height={h}
            rx={1.5}
            className={cn(style.fillClass, 'transition-all duration-500')}
          >
            <title>{`${d.label}: ${d.value}`}</title>
          </rect>
        );
      })}
      {/* baseline */}
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
