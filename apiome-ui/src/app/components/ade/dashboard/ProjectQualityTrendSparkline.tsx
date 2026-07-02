'use client';

import { useId } from 'react';
import { buildQualityTrendPoints, type ProjectQualitySnapshot } from '../../../utils/project-quality-score-history';

interface ProjectQualityTrendSparklineProps {
  history: ProjectQualitySnapshot[];
  className?: string;
}

/** Inline SVG trend (0–100 quality over time). */
export function ProjectQualityTrendSparkline({ history, className }: ProjectQualityTrendSparklineProps) {
  const gradId = `pqspark-${useId().replace(/\W/g, '')}`;
  const overalls = history.map((h) => h.overall);
  const points = buildQualityTrendPoints(overalls);
  if (points.length === 0) return null;

  const d = points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x.toFixed(2)} ${p.y.toFixed(2)}`).join(' ');
  const last = overalls[overalls.length - 1];
  const summary = `${overalls.length} snapshot${overalls.length === 1 ? '' : 's'}, latest ${last}`;

  return (
    <svg
      viewBox="0 0 100 100"
      preserveAspectRatio="none"
      className={`text-indigo-500 dark:text-indigo-400 ${className ?? ''}`}
      aria-hidden
      focusable="false"
    >
      <title>{summary}</title>
      <defs>
        <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="currentColor" stopOpacity={0.22} />
          <stop offset="100%" stopColor="currentColor" stopOpacity={0} />
        </linearGradient>
      </defs>
      <path
        d={`${d} L 100 100 L 0 100 Z`}
        fill={`url(#${gradId})`}
      />
      <path d={d} fill="none" stroke="currentColor" strokeWidth={3} vectorEffect="non-scaling-stroke" />
    </svg>
  );
}
