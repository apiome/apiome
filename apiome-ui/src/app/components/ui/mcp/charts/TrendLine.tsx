'use client';

import * as React from 'react';
import { cn } from '../../../../../../lib/utils';
import { ChartFrame } from './ChartFrame';
import { chartSeriesStyle, type ChartSeriesTone, CHART_SURFACE } from './chartTokens';
import { maxValue, pointsToPath, pointsToSegments, trendLinePoints } from './chartGeometry';

/** Internal viewBox — marks are laid out in this space, then scaled to the container. */
const W = 240;
const H = 64;
const PAD = 6;

/** The x of the `index`-th of `count` evenly-spaced points (a lone point sits at the centre). */
function xAt(index: number, count: number, width: number, padding: number): number {
  const innerW = Math.max(1, width - padding * 2);
  if (count <= 1) return padding + innerW / 2;
  return padding + (innerW / (count - 1)) * index;
}

export interface TrendLineProps {
  /**
   * The series to plot (left→right). An entry may be `null` — a **gap** the line breaks across
   * (e.g. an unscored version), rather than being drawn as `0`. Non-finite numbers are treated as
   * gaps too.
   */
  data: readonly (number | null)[];
  /** Line/area color; defaults to `indigo`. Consumers pass a tone, never a color. */
  tone?: ChartSeriesTone;
  /** Fixed y-axis maximum (e.g. `100` for a 0–100 score); when omitted the series scales to its max. */
  domainMax?: number;
  /** Whether to fill the area under the line (default true). */
  area?: boolean;
  /**
   * Indices at which to overlay a vertical marker (e.g. the versions that introduced a breaking
   * change). Out-of-range indices are ignored. Painted in {@link markerTone}.
   */
  markers?: readonly number[];
  /** Marker color; defaults to `red`. */
  markerTone?: ChartSeriesTone;
  /** Accessible name; defaults to a generated summary. */
  title?: string;
  /** Per-point accessible label for the data table (index, value). Defaults to the raw value. */
  pointLabel?: (index: number, value: number | null) => string;
  /** Extra classes for the wrapping figure (set height here, e.g. `h-24 w-full`). */
  className?: string;
}

/**
 * `<TrendLine>` — a gapped line/area chart for a metric measured across an ordered axis (a quality
 * score or a capability count over discovery snapshots). Unlike {@link Sparkline} it:
 *
 * - **gaps** a `null`/non-finite entry (breaks the line, plots a hollow tick) rather than drawing it
 *   as `0`, so a missing measurement never reads as a crash to zero (V2-MCP-30.4); and
 * - overlays optional vertical **markers** at given indices (e.g. breaking-change releases), aligned
 *   to the same x-grid the points sit on, so a marker always lines up with its version.
 *
 * Every real point gets a dot so an isolated value between two gaps is still visible. Colors resolve
 * from token tones (no hex literals); empty data renders the shared empty state; responsive via
 * `viewBox`; SSR-safe (gradient id from `React.useId`).
 */
export function TrendLine({
  data,
  tone = 'indigo',
  domainMax,
  area = true,
  markers = [],
  markerTone = 'red',
  title,
  pointLabel,
  className,
}: TrendLineProps) {
  const gradId = `trendline-${React.useId().replace(/[^a-zA-Z0-9]/g, '')}`;
  const style = chartSeriesStyle(tone);
  const markerStyle = chartSeriesStyle(markerTone);

  const present = data.filter((v): v is number => typeof v === 'number' && Number.isFinite(v));
  // "No line to draw" — every entry is a gap (or the series is empty). Render the empty state so the
  // panel never shows a blank frame.
  const isEmpty = present.length === 0;

  const points = trendLinePoints(data, W, H, PAD, domainMax);
  const segments = pointsToSegments(points);
  const dots = points.filter((p): p is NonNullable<typeof p> => p !== null);
  const markerIndices = markers.filter((i) => Number.isInteger(i) && i >= 0 && i < data.length);

  const last = present.length ? present[present.length - 1] : null;
  const gaps = data.length - present.length;
  const summary =
    last === null
      ? 'No data'
      : `${present.length} of ${data.length} point${data.length === 1 ? '' : 's'} measured` +
        `, latest ${last}, max ${maxValue(present)}` +
        (gaps ? `, ${gaps} gap${gaps === 1 ? '' : 's'}` : '') +
        (markerIndices.length ? `, ${markerIndices.length} marker${markerIndices.length === 1 ? '' : 's'}` : '');
  const label = title ?? `Trend — ${summary}`;

  return (
    <ChartFrame
      title={label}
      description={summary}
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="none"
      isEmpty={isEmpty}
      className={cn('h-24 w-full', className)}
      tableFallback={
        <table>
          <caption>{label}</caption>
          <tbody>
            {data.map((v, i) => (
              <tr key={i}>
                <th scope="row">{i + 1}</th>
                <td>{pointLabel ? pointLabel(i, v) : v === null ? 'no data' : v}</td>
                <td>{markerIndices.includes(i) ? 'marker' : ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      }
    >
      {/* Markers first, so the line and its dots sit above them. */}
      <g className={markerStyle.textClass}>
        {markerIndices.map((i) => {
          const x = xAt(i, data.length, W, PAD);
          return (
            <g key={`m-${i}`}>
              <line
                x1={x}
                y1={PAD}
                x2={x}
                y2={H - PAD}
                stroke="currentColor"
                strokeWidth={1.5}
                strokeDasharray="3 2"
                strokeOpacity={0.7}
                vectorEffect="non-scaling-stroke"
              />
              {/* A small solid diamond at the top pins the marker so it reads even over the area fill. */}
              <path
                d={`M ${x.toFixed(2)} ${(PAD - 3).toFixed(2)} l 3 3 l -3 3 l -3 -3 Z`}
                fill="currentColor"
              />
            </g>
          );
        })}
      </g>

      <g className={style.textClass}>
        {area ? (
          <>
            {/* One shared gradient for every area segment; hoisted so a leading single-point run
                (which draws no area) can't leave a later run referencing a missing gradient id. */}
            <defs>
              <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="currentColor" stopOpacity={0.22} />
                <stop offset="100%" stopColor="currentColor" stopOpacity={0} />
              </linearGradient>
            </defs>
            {segments.map((seg, si) =>
              seg.length >= 2 ? (
                <path
                  key={`a-${si}`}
                  d={`${pointsToPath(seg)} L ${seg[seg.length - 1].x.toFixed(2)} ${H - PAD} L ${seg[0].x.toFixed(2)} ${H - PAD} Z`}
                  fill={`url(#${gradId})`}
                  stroke="none"
                />
              ) : null,
            )}
          </>
        ) : null}

        {segments.map((seg, si) => (
          <path
            key={`l-${si}`}
            d={pointsToPath(seg)}
            fill="none"
            stroke="currentColor"
            strokeWidth={2}
            strokeLinecap="round"
            strokeLinejoin="round"
            vectorEffect="non-scaling-stroke"
          />
        ))}

        {dots.map((p, i) => (
          <circle key={`d-${i}`} cx={p.x} cy={p.y} r={2.5} fill="currentColor" />
        ))}
      </g>

      {/* A faint baseline so a mostly-flat or gappy series still reads as sitting on an axis. */}
      <line
        x1={PAD}
        y1={H - PAD}
        x2={W - PAD}
        y2={H - PAD}
        className={CHART_SURFACE.trackStrokeClass}
        strokeWidth={1}
        vectorEffect="non-scaling-stroke"
      />
    </ChartFrame>
  );
}
