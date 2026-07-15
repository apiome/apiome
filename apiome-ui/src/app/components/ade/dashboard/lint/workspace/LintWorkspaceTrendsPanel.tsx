'use client';

/**
 * Remediation-vs-policy trends panel (CLX-4.1, #4859).
 *
 * Renders the daily series with an explicit visual split between **remediation** (new vs
 * genuinely fixed findings) and **policy & waivers** (grants, expiries, false positives,
 * policy pack publications) — the two are never summed into one line, which is what lets a
 * team prove a posture change came from fixes rather than from loosening policy (AC-4).
 */

import React from 'react';
import { TrendLine } from '@/app/components/ui/mcp/charts/TrendLine';
import type { LintWorkspaceTrends } from '@/app/utils/lint-workspace';
import { dashboardPanelPaddedClass } from '../../dashboardScreenClasses';
import { cn } from '@lib/utils';

const seriesTitleClass = 'text-sm font-medium text-gray-900 dark:text-gray-100';
const seriesTotalClass = 'text-xs text-gray-500 dark:text-gray-400';

interface SeriesSpec {
  key: keyof Omit<LintWorkspaceTrends['series'][number], 'date'>;
  label: string;
  tone: 'red' | 'emerald' | 'amber' | 'violet' | 'indigo' | 'cyan';
}

const REMEDIATION_SERIES: SeriesSpec[] = [
  { key: 'newFindings', label: 'New findings', tone: 'red' },
  { key: 'remediatedFindings', label: 'Remediated (genuine fixes)', tone: 'emerald' },
];

const POLICY_SERIES: SeriesSpec[] = [
  { key: 'waiversGranted', label: 'Waivers granted', tone: 'amber' },
  { key: 'waiversExpired', label: 'Waivers expired', tone: 'cyan' },
  { key: 'markedFalsePositive', label: 'Marked false positive', tone: 'violet' },
  { key: 'policyPackPublications', label: 'Policy pack publications', tone: 'indigo' },
];

function SeriesChart({ spec, trends }: { spec: SeriesSpec; trends: LintWorkspaceTrends }) {
  const data = trends.series.map((point) => point[spec.key]);
  const total = data.reduce((sum, v) => sum + v, 0);
  return (
    <div data-testid={`trend-${spec.key}`}>
      <div className="flex items-baseline justify-between">
        <span className={seriesTitleClass}>{spec.label}</span>
        <span className={seriesTotalClass}>{total} in {trends.days}d</span>
      </div>
      <TrendLine
        data={data}
        tone={spec.tone}
        className="h-16 w-full"
        title={`${spec.label} per day over the last ${trends.days} days`}
        pointLabel={(index, value) => `${trends.series[index]?.date}: ${value ?? 0}`}
      />
    </div>
  );
}

export interface LintWorkspaceTrendsPanelProps {
  trends: LintWorkspaceTrends;
}

/** The Trends tab body. */
export default function LintWorkspaceTrendsPanel({ trends }: LintWorkspaceTrendsPanelProps) {
  return (
    <div data-testid="lint-workspace-trends" className="grid gap-4 lg:grid-cols-2">
      <section className={cn(dashboardPanelPaddedClass, 'space-y-4')}>
        <h2 className="text-sm font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400">
          Remediation
        </h2>
        {REMEDIATION_SERIES.map((spec) => (
          <SeriesChart key={spec.key} spec={spec} trends={trends} />
        ))}
        <p className="text-xs text-gray-500 dark:text-gray-400">
          “Remediated” counts findings that disappeared from evidence without being waived or
          marked false positive — genuine fixes only.
        </p>
      </section>
      <section className={cn(dashboardPanelPaddedClass, 'space-y-4')}>
        <h2 className="text-sm font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400">
          Policy &amp; waivers
        </h2>
        {POLICY_SERIES.map((spec) => (
          <SeriesChart key={spec.key} spec={spec} trends={trends} />
        ))}
        <p className="text-xs text-gray-500 dark:text-gray-400">
          Policy and waiver activity is kept separate from remediation so posture changes are
          attributable to fixes, not rule changes.
        </p>
      </section>
    </div>
  );
}
