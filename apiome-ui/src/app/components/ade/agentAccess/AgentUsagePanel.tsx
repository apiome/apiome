'use client';

import * as React from 'react';
import { Activity } from 'lucide-react';

import { EmptyState } from '@/app/components/ui/EmptyState';
import { ErrorState } from '@/app/components/ui/ErrorState';
import { LoadingState } from '@/app/components/ui/LoadingState';
import { Segmented, SegmentedItem } from '@/app/components/ui/Segmented';
import { BarSeries, TrendLine } from '@/app/components/ui/mcp/charts';
import { Stat, StatGrid } from '@/app/components/ui/metrics';

import {
  formatCount,
  formatDay,
  formatLatency,
  formatRate,
  topBars,
  usageAgentLabel,
  usageDailySeries,
  usageIsEmpty,
  USAGE_RANGES,
  type AgentUsage,
  type AgentUsageMetrics,
} from './agentAccessModel';

/**
 * Agent usage charts — AGX-3.4 (#4540), over the AGX-3.3 daily rollups.
 *
 * A range picker (7 / 30 / 90 days), four totals, three daily trends (calls, error rate,
 * latency) and two rankings (calls per tool, top agents), each ranking followed by a table
 * with every entry's calls, error rate and latency. The charts are the MCP chart kit's
 * `TrendLine` and `BarSeries`, which carry their own accessible data tables.
 *
 * **Empty is a state, not a blank chart**: a window with no calls says so once, and says why
 * that is likely (no key has been used yet), instead of drawing five flat lines.
 */

/** Props for {@link AgentUsagePanel}. */
export interface AgentUsagePanelProps {
  usage: AgentUsage | null;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
  /** The window, in days. */
  days: number;
  onDaysChange: (days: number) => void;
}

/**
 * One ranking's table: every entry with calls, errors and latency.
 *
 * @param props - The caption, the rows and how to name a row.
 * @returns The table.
 */
function UsageTable<T extends AgentUsageMetrics>({
  caption,
  heading,
  rows,
  label,
  testId,
}: {
  caption: string;
  heading: string;
  rows: readonly T[];
  label: (row: T) => string;
  testId: string;
}) {
  return (
    <div className="agx-table-wrap">
      <table className="agx-table" data-testid={testId}>
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr>
            <th scope="col">{heading}</th>
            <th scope="col" className="agx-num">
              Calls
            </th>
            <th scope="col" className="agx-num">
              Error rate
            </th>
            <th scope="col" className="agx-num">
              Avg latency
            </th>
            <th scope="col" className="agx-num">
              Worst p95
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const name = label(row);
            return (
              <tr key={name}>
                <th scope="row" className="agx-cell-mono mono">
                  {name}
                </th>
                <td className="agx-num">{formatCount(row.calls)}</td>
                <td className="agx-num">{formatRate(row.errorRate)}</td>
                <td className="agx-num">{formatLatency(row.latencyAvgMs)}</td>
                <td className="agx-num">{formatLatency(row.latencyP95MaxMs)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/**
 * A titled chart card.
 *
 * @param props - The title, an optional note, and the chart.
 * @returns The card.
 */
function ChartCard({
  title,
  note,
  children,
  testId,
}: {
  title: string;
  note?: string;
  children: React.ReactNode;
  testId: string;
}) {
  return (
    <section className="agx-chart-card" aria-label={title} data-testid={testId}>
      <h3 className="agx-section-title">{title}</h3>
      {note && <p className="agx-hint">{note}</p>}
      {children}
    </section>
  );
}

/**
 * The usage panel.
 *
 * @param props See {@link AgentUsagePanelProps}.
 * @returns The range picker and the charts, or the loading / error / empty state.
 */
export default function AgentUsagePanel({
  usage,
  loading,
  error,
  onRetry,
  days,
  onDaysChange,
}: AgentUsagePanelProps) {
  let body: React.ReactNode;
  if (error) {
    body = (
      <ErrorState
        title="Usage could not be loaded"
        description={error}
        onRetry={onRetry}
        data-testid="agx-usage-error"
      />
    );
  } else if (!usage) {
    body = <LoadingState message="Loading usage…" data-testid="agx-usage-loading" />;
  } else if (usageIsEmpty(usage)) {
    body = (
      <EmptyState
        icon={<Activity aria-hidden />}
        title="No agent calls in this period"
        description="Charts appear once an agent calls a tool with one of your agent keys. Usage is rolled up by UTC day."
        data-testid="agx-usage-empty"
      />
    );
  } else {
    const series = usageDailySeries(usage);
    const dayLabel = (index: number) => formatDay(usage.daily[index]?.day ?? '');
    const range = `${formatDay(usage.startDay)} – ${formatDay(usage.endDay)}`;
    body = (
      <div className="agx-usage" data-testid="agx-usage">
        <StatGrid columns={4}>
          <Stat label="Calls" value={formatCount(usage.totals.calls)} footnote={range} />
          <Stat
            label="Error rate"
            value={formatRate(usage.totals.errorRate)}
            footnote={`${formatCount(usage.totals.errors)} failed · ${formatCount(usage.totals.quotaRejections)} over quota`}
          />
          <Stat
            label="Avg latency"
            value={formatLatency(usage.totals.latencyAvgMs)}
            footnote={`Worst p95 ${formatLatency(usage.totals.latencyP95MaxMs)}`}
          />
          <Stat
            label="Active agents"
            value={formatCount(usage.agents.length)}
            footnote={`${formatCount(usage.tools.length)} tools called`}
          />
        </StatGrid>

        <div className="agx-chart-grid">
          <ChartCard title="Calls per day" testId="agx-chart-calls">
            <TrendLine
              data={series.calls}
              tone="indigo"
              title="Calls per day"
              pointLabel={(i, v) => `${dayLabel(i)}: ${v ?? 0} calls`}
              className="agx-chart"
            />
          </ChartCard>
          <ChartCard
            title="Error rate per day"
            note="Days without calls are gaps."
            testId="agx-chart-errors"
          >
            <TrendLine
              data={series.errorRatePct}
              tone="red"
              domainMax={100}
              title="Error rate per day (%)"
              pointLabel={(i, v) => `${dayLabel(i)}: ${v === null ? 'no calls' : `${v}%`}`}
              className="agx-chart"
            />
          </ChartCard>
          <ChartCard
            title="Average latency per day"
            note="Milliseconds, weighted by calls."
            testId="agx-chart-latency"
          >
            <TrendLine
              data={series.latencyAvgMs}
              tone="violet"
              title="Average latency per day (ms)"
              pointLabel={(i, v) => `${dayLabel(i)}: ${v === null ? 'no calls' : `${v} ms`}`}
              className="agx-chart"
            />
          </ChartCard>
        </div>

        <div className="agx-chart-grid agx-chart-grid--two">
          <ChartCard title="Calls per tool" testId="agx-chart-tools">
            <BarSeries
              data={topBars(usage.tools, (t) => t.toolName)}
              tone="emerald"
              title="Calls per tool (top tools)"
              className="agx-chart agx-chart--bars"
            />
            <UsageTable
              caption="Calls per tool"
              heading="Tool"
              rows={usage.tools}
              label={(t) => t.toolName}
              testId="agx-usage-tools-table"
            />
          </ChartCard>
          <ChartCard title="Top agents" testId="agx-chart-agents">
            <BarSeries
              data={topBars(usage.agents, usageAgentLabel)}
              tone="amber"
              title="Calls per agent key (top agents)"
              className="agx-chart agx-chart--bars"
            />
            <UsageTable
              caption="Calls per agent key"
              heading="Agent key"
              rows={usage.agents}
              label={usageAgentLabel}
              testId="agx-usage-agents-table"
            />
          </ChartCard>
        </div>
      </div>
    );
  }

  return (
    <section
      className="agx-panel"
      aria-label="Usage"
      aria-busy={loading || undefined}
      data-testid="agx-usage-panel"
    >
      <div className="agx-toolbar">
        <span className="agx-legend" id="agx-usage-range">
          Period
        </span>
        <Segmented
          aria-labelledby="agx-usage-range"
          value={String(days)}
          size="sm"
          onValueChange={(value) => onDaysChange(Number(value))}
          data-testid="agx-usage-range"
        >
          {USAGE_RANGES.map((range) => (
            <SegmentedItem key={range.days} value={String(range.days)}>
              {range.label}
            </SegmentedItem>
          ))}
        </Segmented>
      </div>
      {body}
    </section>
  );
}
