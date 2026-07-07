'use client';

import * as React from 'react';
import { cn } from '../../../../../../lib/utils';
import { ChartFrame } from './ChartFrame';
import { chartSeriesStyle, type ChartSeriesTone, CHART_SURFACE } from './chartTokens';
import { intensity, maxValue } from './chartGeometry';

const CELL = 16;
const GAP = 2;

export interface HeatmapProps {
  /** Row-major matrix of values; each inner array is one row. Ragged rows are allowed. */
  matrix: readonly (readonly number[])[];
  /** Optional row labels (rendered to assistive tech via the fallback table). */
  rowLabels?: readonly string[];
  /** Optional column labels. */
  colLabels?: readonly string[];
  /** Fixed intensity maximum; when omitted the largest cell defines full intensity. */
  domainMax?: number;
  /** Cell color; intensity is expressed as fill-opacity so it stays a single token tone. */
  tone?: ChartSeriesTone;
  /** Accessible name; defaults to a generated summary. */
  title?: string;
  /** Extra classes for the wrapping figure. */
  className?: string;
}

/**
 * `<Heatmap>` — a value-intensity grid for two-dimensional density (activity by day×hour, error rate
 * by tool×version). Every cell paints the same token `tone`; magnitude is shown as fill-opacity
 * (0.08→1) relative to the matrix max, so the palette stays a single color and honors dark mode. An
 * empty matrix renders the shared empty state. Responsive via `viewBox`; SSR-safe.
 */
export function Heatmap({
  matrix,
  rowLabels,
  colLabels,
  domainMax,
  tone = 'indigo',
  title,
  className,
}: HeatmapProps) {
  const rows = matrix.length;
  const cols = matrix.reduce((m, r) => Math.max(m, r.length), 0);
  const isEmpty = rows === 0 || cols === 0;
  const style = chartSeriesStyle(tone);

  const flat = matrix.flatMap((r) => r.slice());
  const max = domainMax && domainMax > 0 ? domainMax : maxValue(flat) || 1;

  const width = cols * CELL + (cols + 1) * GAP;
  const height = rows * CELL + (rows + 1) * GAP;

  const summary = `${rows}×${cols} grid, max ${maxValue(flat)}`;
  const label = title ?? `Heatmap — ${summary}`;

  return (
    <ChartFrame
      title={label}
      description={summary}
      viewBox={`0 0 ${Math.max(1, width)} ${Math.max(1, height)}`}
      isEmpty={isEmpty}
      className={cn('h-40 w-full', className)}
      tableFallback={
        <table>
          <caption>{label}</caption>
          {colLabels ? (
            <thead>
              <tr>
                <td />
                {colLabels.map((c, i) => (
                  <th key={i} scope="col">
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
          ) : null}
          <tbody>
            {matrix.map((row, r) => (
              <tr key={r}>
                <th scope="row">{rowLabels?.[r] ?? `Row ${r + 1}`}</th>
                {row.map((v, c) => (
                  <td key={c}>{v}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      }
    >
      {matrix.map((row, r) =>
        Array.from({ length: cols }, (_, c) => {
          const value = row[c] ?? 0;
          const t = intensity(value, max);
          const x = GAP + c * (CELL + GAP);
          const y = GAP + r * (CELL + GAP);
          const rLabel = rowLabels?.[r] ?? `Row ${r + 1}`;
          const cLabel = colLabels?.[c] ?? `Col ${c + 1}`;
          return (
            <rect
              key={`${r}-${c}`}
              x={x}
              y={y}
              width={CELL}
              height={CELL}
              rx={2}
              // A near-zero cell shows the muted track tone; anything above uses the series tone at
              // an opacity floored to 0.08 so a small-but-present value is still visible.
              className={t <= 0 ? CHART_SURFACE.trackFillClass : style.fillClass}
              fillOpacity={t <= 0 ? undefined : 0.08 + t * 0.92}
            >
              <title>{`${rLabel} × ${cLabel}: ${value}`}</title>
            </rect>
          );
        }),
      )}
    </ChartFrame>
  );
}
