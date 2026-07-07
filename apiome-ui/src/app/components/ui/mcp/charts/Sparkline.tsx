'use client';

import * as React from 'react';
import { cn } from '../../../../../../lib/utils';
import { ChartFrame } from './ChartFrame';
import { chartSeriesStyle, type ChartSeriesTone } from './chartTokens';
import { maxValue, pointsToPath, sparklinePoints } from './chartGeometry';

/** Internal viewBox — chart marks are laid out in this space, then scaled to the container. */
const W = 120;
const H = 40;
const PAD = 3;

export interface SparklineProps {
  /** The series to plot (left→right). Non-finite entries are treated as 0. */
  data: readonly number[];
  /** Series color; defaults to `indigo`. Consumers pass a tone, never a color. */
  tone?: ChartSeriesTone;
  /** Fixed y-axis maximum; when omitted the series scales to its own max. */
  domainMax?: number;
  /** Whether to fill the area under the line (default true). */
  area?: boolean;
  /** Accessible name; defaults to a generated summary. */
  title?: string;
  /** Extra classes for the wrapping figure (set height here, e.g. `h-10 w-32`). */
  className?: string;
}

/**
 * `<Sparkline>` — a compact, axis-free trend line for inline "how is this moving" signals (grade
 * over versions, latency over time). Scales to its own max unless `domainMax` is pinned, fills the
 * area beneath by default, and resolves its color from a token tone. Empty data renders the shared
 * empty state. Responsive via `viewBox`; SSR-safe (the gradient id comes from `React.useId`).
 */
export function Sparkline({
  data,
  tone = 'indigo',
  domainMax,
  area = true,
  title,
  className,
}: SparklineProps) {
  const gradId = `sparkline-${React.useId().replace(/[^a-zA-Z0-9]/g, '')}`;
  const style = chartSeriesStyle(tone);
  const isEmpty = data.length === 0;
  const points = sparklinePoints(data, W, H, PAD, domainMax);
  const linePath = pointsToPath(points);
  const areaPath = points.length
    ? `${linePath} L ${points[points.length - 1].x.toFixed(2)} ${H} L ${points[0].x.toFixed(2)} ${H} Z`
    : '';

  const last = data.length ? data[data.length - 1] : null;
  const summary =
    last === null
      ? 'No data'
      : `${data.length} point${data.length === 1 ? '' : 's'}, latest ${last}, max ${maxValue(data)}`;
  const label = title ?? `Trend — ${summary}`;

  return (
    <ChartFrame
      title={label}
      description={summary}
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="none"
      isEmpty={isEmpty}
      className={cn('h-10 w-32', className)}
      tableFallback={
        <table>
          <caption>{label}</caption>
          <tbody>
            {data.map((v, i) => (
              <tr key={i}>
                <th scope="row">{i + 1}</th>
                <td>{v}</td>
              </tr>
            ))}
          </tbody>
        </table>
      }
    >
      <g className={style.textClass}>
        {area && areaPath ? (
          <>
            <defs>
              <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="currentColor" stopOpacity={0.22} />
                <stop offset="100%" stopColor="currentColor" stopOpacity={0} />
              </linearGradient>
            </defs>
            <path d={areaPath} fill={`url(#${gradId})`} stroke="none" />
          </>
        ) : null}
        <path
          d={linePath}
          fill="none"
          stroke="currentColor"
          strokeWidth={2}
          strokeLinecap="round"
          strokeLinejoin="round"
          vectorEffect="non-scaling-stroke"
        />
      </g>
    </ChartFrame>
  );
}
