'use client';

import * as React from 'react';
import { cn } from '../../../../../../lib/utils';
import { ChartFrame } from './ChartFrame';
import { chartSeriesStyle, type ChartSeriesTone, CHART_SURFACE } from './chartTokens';
import { maxValue, polarToCartesian, polygonPoints, radarPoints } from './chartGeometry';

/** One radar axis: its label and value. */
export interface RadarAxis {
  label: string;
  value: number;
}

const SIZE = 140;
const CENTER = SIZE / 2;
const R = 52;
const RINGS = 4;

export interface RadarProps {
  /** The axes (spokes), placed clockwise from the top. Needs ≥ 3 to form a polygon. */
  axes: readonly RadarAxis[];
  /** Fixed axis maximum; when omitted the largest value defines the outer ring. */
  max?: number;
  /** Fill/outline color; defaults to `indigo`. */
  tone?: ChartSeriesTone;
  /** Accessible name; defaults to a generated summary. */
  title?: string;
  /** Extra classes for the wrapping figure (set size here). */
  className?: string;
}

/**
 * `<Radar>` — a multi-axis profile for comparing several normalized dimensions at once (a server's
 * documentation / annotation / complexity / safety coverage). Draws a concentric web, one spoke per
 * axis, and the filled value polygon. Values scale to `max` (or the largest value). Fewer than three
 * axes, or all-zero values, render the shared empty state. Responsive via `viewBox`; SSR-safe.
 */
export function Radar({ axes, max, tone = 'indigo', title, className }: RadarProps) {
  const values = axes.map((a) => a.value);
  const domainMax = max && max > 0 ? max : maxValue(values);
  const isEmpty = axes.length < 3 || domainMax <= 0;
  const style = chartSeriesStyle(tone);

  const verts = radarPoints(values, domainMax, CENTER, CENTER, R);
  const polygon = polygonPoints(verts);

  const summary = axes.map((a) => `${a.label}: ${a.value}`).join(', ') || 'No data';
  const label = title ?? `Radar chart — ${summary}`;

  return (
    <ChartFrame
      title={label}
      description={summary}
      viewBox={`0 0 ${SIZE} ${SIZE}`}
      isEmpty={isEmpty}
      className={cn('h-36 w-36', className)}
      tableFallback={
        <table>
          <caption>{label}</caption>
          <tbody>
            {axes.map((a, i) => (
              <tr key={i}>
                <th scope="row">{a.label}</th>
                <td>{a.value}</td>
              </tr>
            ))}
          </tbody>
        </table>
      }
    >
      {/* concentric web rings */}
      {Array.from({ length: RINGS }, (_, ring) => {
        const rr = (R * (ring + 1)) / RINGS;
        const ringPts = polygonPoints(
          axes.map((_, i) => polarToCartesian(CENTER, CENTER, rr, (360 / axes.length) * i)),
        );
        return (
          <polygon
            key={ring}
            points={ringPts}
            fill="none"
            strokeWidth={0.5}
            vectorEffect="non-scaling-stroke"
            className={CHART_SURFACE.trackStrokeClass}
          />
        );
      })}
      {/* spokes */}
      {axes.map((_, i) => {
        const end = polarToCartesian(CENTER, CENTER, R, (360 / axes.length) * i);
        return (
          <line
            key={i}
            x1={CENTER}
            y1={CENTER}
            x2={end.x}
            y2={end.y}
            strokeWidth={0.5}
            vectorEffect="non-scaling-stroke"
            className={CHART_SURFACE.trackStrokeClass}
          />
        );
      })}
      {/* value polygon */}
      <polygon
        points={polygon}
        className={cn(style.fillClass, style.strokeClass)}
        fillOpacity={0.25}
        strokeWidth={1.5}
        vectorEffect="non-scaling-stroke"
      />
    </ChartFrame>
  );
}
