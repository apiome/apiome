/**
 * The building blocks of the **Health** pages (PFX-6.3, #6955): the state badge, the KPI strip,
 * the pairs table, a pair's signals, and its trend charts and table.
 *
 * Every chart is drawn as SVG from `@lib/pact-health`'s geometry with CSS classes only (no inline
 * colours), and every chart is backed by the **Trend** table, so nothing is shown only as a picture.
 */

import * as React from 'react';
import Link from 'next/link';
import { Badge } from '@/app/components/ui/Badge';
import { formatWhen, shortVersion } from '@lib/pact-pacticipants';
import { shortSha } from '@lib/pact-detail';
import {
  CHART,
  chartPath,
  chartPoints,
  concerns,
  formatDay,
  formatDuration,
  formatShare,
  healthStateText,
  pairHealthRoute,
  signalLabel,
  signalStatusText,
  type HealthComponent,
  type HealthCounts,
  type PairHealth,
  type PairMetrics,
  type TrendBucket,
} from '@lib/pact-health';

/**
 * A pair's state as a badge.
 *
 * @param props - The state.
 * @returns The badge.
 */
export function HealthStateBadge({ state }: { state: string }) {
  const text = healthStateText(state);
  return (
    <Badge variant={text.variant} data-testid="phx-state" title={text.description}>
      {text.label}
    </Badge>
  );
}

/**
 * The KPI strip: pairs per state, and the window's pass rate, flakiness and mean duration.
 *
 * @param props - The counts and the totals.
 * @returns The strip.
 */
export function HealthKpis({ counts, totals }: { counts: HealthCounts; totals: PairMetrics }) {
  const items: Array<[string, string, string]> = [
    ['pairs', 'Pairs', String(counts.pairs)],
    ['healthy', 'Healthy', String(counts.healthy)],
    ['degraded', 'Degraded', String(counts.degraded)],
    ['failing', 'Failing', String(counts.failing)],
    ['unknown', 'Unknown', String(counts.unknown)],
    ['pass-rate', 'Pass rate', formatShare(totals.pass_rate)],
    ['flakiness', 'Flakiness', formatShare(totals.flakiness)],
    ['duration', 'Mean duration', formatDuration(totals.mean_duration_ms)],
  ];
  return (
    <dl className="pvx-kpis" data-testid="phx-kpis">
      {items.map(([key, label, value]) => (
        <div key={key} className={`pvx-kpi phx-kpi--${key}`} data-testid={`phx-kpi-${key}`}>
          <dt>{label}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

/**
 * One pair's analytics over the window: runs, failures, pass rate, flips, flakiness, mean duration.
 *
 * @param props - The metrics.
 * @returns The strip.
 */
export function MetricsKpis({ metrics }: { metrics: PairMetrics }) {
  const items: Array<[string, string, string]> = [
    ['runs', 'Runs', String(metrics.runs)],
    ['failed', 'Failed', String(metrics.failed)],
    ['pass-rate', 'Pass rate', formatShare(metrics.pass_rate)],
    ['flips', 'Verdict flips', String(metrics.flips)],
    ['flakiness', 'Flakiness', formatShare(metrics.flakiness)],
    ['duration', 'Mean duration', formatDuration(metrics.mean_duration_ms)],
  ];
  return (
    <dl className="pvx-kpis" data-testid="phx-metrics">
      {items.map(([key, label, value]) => (
        <div key={key} className={`pvx-kpi phx-kpi--${key}`} data-testid={`phx-metric-${key}`}>
          <dt>{label}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

/**
 * What is wrong with a pair, in a few words: each failing or warning signal's name.
 *
 * @param props - The pair.
 * @returns The list, or a muted "No concerns".
 */
export function Concerns({ pair }: { pair: Pick<PairHealth, 'components'> }) {
  const items = concerns(pair);
  if (items.length === 0) return <span className="ppx__muted">No concerns</span>;
  return (
    <ul className="phx-concerns" data-testid="phx-concerns">
      {items.map((component) => (
        <li
          key={component.key}
          className={`phx-concern phx-concern--${component.status}`}
          title={component.summary}
        >
          {signalLabel(component.key)}
        </li>
      ))}
    </ul>
  );
}

/**
 * Every pair, worst first.
 *
 * @param props - The pairs and the window their links keep.
 * @returns The table.
 */
export function PairsTable({ pairs, window }: { pairs: PairHealth[]; window: string }) {
  return (
    <div className="ppx__table-wrap">
      <table className="ppx__table" data-testid="phx-pairs-table">
        <caption className="sr-only">
          Each consumer and provider pair&apos;s contract health, worst first
        </caption>
        <thead>
          <tr>
            <th scope="col">Pair</th>
            <th scope="col">Health</th>
            <th scope="col">Concerns</th>
            <th scope="col">Runs</th>
            <th scope="col">Pass rate</th>
            <th scope="col">Flakiness</th>
            <th scope="col">Mean duration</th>
            <th scope="col">Last verified</th>
          </tr>
        </thead>
        <tbody>
          {pairs.map((pair) => (
            <tr
              key={`${pair.provider}/${pair.consumer}`}
              data-testid={`phx-pair-${pair.provider}-${pair.consumer}`}
            >
              <th scope="row">
                <Link
                  className="ppx__link ppx__name"
                  href={pairHealthRoute(pair.provider, pair.consumer, window)}
                >
                  {pair.consumer_name} → {pair.provider_name}
                </Link>
              </th>
              <td>
                <HealthStateBadge state={pair.state} />
              </td>
              <td>
                <Concerns pair={pair} />
              </td>
              <td className="ppx__mono">{pair.metrics.runs}</td>
              <td className="ppx__mono">{formatShare(pair.metrics.pass_rate)}</td>
              <td className="ppx__mono">{formatShare(pair.metrics.flakiness)}</td>
              <td className="ppx__mono">{formatDuration(pair.metrics.mean_duration_ms)}</td>
              <td className="ppx__when">
                {pair.latest_verified_at ? formatWhen(pair.latest_verified_at) : 'Never'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * A pair's signals: each one's status and why.
 *
 * @param props - The components.
 * @returns The list.
 */
export function SignalList({ components }: { components: HealthComponent[] }) {
  return (
    <ul className="phx-signals" data-testid="phx-signals">
      {components.map((component) => {
        const status = signalStatusText(component.status);
        return (
          <li
            key={component.key}
            className="phx-signal"
            data-testid={`phx-signal-${component.key}`}
          >
            <span className="phx-signal__name">{signalLabel(component.key)}</span>
            <Badge variant={status.variant} data-testid="phx-signal-status">
              {status.label}
            </Badge>
            <span className="phx-signal__why">{component.summary}</span>
            <code className="phx-signal__code">{component.code}</code>
          </li>
        );
      })}
    </ul>
  );
}

/**
 * The pair's facts: the newest pact and its latest verdict.
 *
 * @param props - The pair.
 * @returns The facts.
 */
export function PairFacts({ pair }: { pair: PairHealth }) {
  return (
    <dl className="prx-facts" data-testid="phx-facts">
      <div>
        <dt>Newest pact</dt>
        <dd className="ppx__mono" title={pair.pact_version_sha}>
          {shortVersion(pair.consumer_version)} · {shortSha(pair.pact_version_sha)}
        </dd>
      </div>
      <div>
        <dt>Published</dt>
        <dd>{formatWhen(pair.published_at)}</dd>
      </div>
      <div>
        <dt>Latest verdict</dt>
        <dd>
          {pair.latest_success === null
            ? 'Not verified yet'
            : pair.latest_success
              ? 'Passed'
              : 'Failed'}
        </dd>
      </div>
      <div>
        <dt>Last verified</dt>
        <dd>{pair.latest_verified_at ? formatWhen(pair.latest_verified_at) : 'Never'}</dd>
      </div>
    </dl>
  );
}

/** One chart: what it draws and how its values read. */
export interface TrendSeries {
  key: 'pass-rate' | 'flakiness' | 'duration';
  title: string;
  values: Array<number | null>;
  max: number;
  format: (value: number | null) => string;
}

/**
 * The three series of a trend: pass rate and flakiness (0 … 100 %), and mean duration (0 … the
 * slowest bucket).
 *
 * @param trend - The buckets, oldest first.
 * @returns The series.
 */
export function trendSeries(trend: TrendBucket[]): TrendSeries[] {
  const durations = trend.map((bucket) => bucket.metrics.mean_duration_ms);
  const slowest = Math.max(
    0,
    ...durations.filter((value): value is number => typeof value === 'number'),
  );
  return [
    {
      key: 'pass-rate',
      title: 'Pass rate',
      values: trend.map((bucket) => bucket.metrics.pass_rate),
      max: 1,
      format: formatShare,
    },
    {
      key: 'flakiness',
      title: 'Flakiness',
      values: trend.map((bucket) => bucket.metrics.flakiness),
      max: 1,
      format: formatShare,
    },
    {
      key: 'duration',
      title: 'Mean duration',
      values: durations,
      max: slowest,
      format: formatDuration,
    },
  ];
}

/**
 * One trend chart: a line through the buckets that have a value, a dot on each, gaps where a bucket
 * has none, and the first and last day under it.
 *
 * @param props - The series and the buckets (for the axis labels).
 * @returns The figure.
 */
export function TrendChart({ series, trend }: { series: TrendSeries; trend: TrendBucket[] }) {
  const points = chartPoints(series.values, series.max);
  const latest = points.length ? points[points.length - 1] : null;
  const baseline = CHART.height - CHART.padY;
  const label = `${series.title} per bucket, ${formatDay(trend[0]?.start)} to ${formatDay(trend[trend.length - 1]?.start)}${
    latest ? `; latest ${series.format(latest.value)}` : '; no data'
  }`;
  return (
    <figure
      className={`phx-chart phx-chart--${series.key}`}
      data-testid={`phx-chart-${series.key}`}
    >
      <figcaption className="phx-chart__title">
        {series.title}
        <span className="phx-chart__latest">
          {latest ? series.format(latest.value) : 'No data'}
        </span>
      </figcaption>
      <svg
        className="phx-chart__svg"
        viewBox={`0 0 ${CHART.width} ${CHART.height}`}
        role="img"
        aria-label={label}
      >
        <line
          className="phx-chart__axis"
          x1={CHART.padX}
          x2={CHART.width - CHART.padX}
          y1={baseline}
          y2={baseline}
        />
        <line
          className="phx-chart__grid"
          x1={CHART.padX}
          x2={CHART.width - CHART.padX}
          y1={CHART.padY}
          y2={CHART.padY}
        />
        {points.length ? <path className="phx-chart__line" d={chartPath(points)} /> : null}
        {points.map((point) => (
          <circle key={point.index} className="phx-chart__dot" cx={point.x} cy={point.y} r={3}>
            <title>
              {formatDay(trend[point.index]?.start)}: {series.format(point.value)}
            </title>
          </circle>
        ))}
      </svg>
      <div className="phx-chart__days" aria-hidden>
        <span>{formatDay(trend[0]?.start)}</span>
        <span>Scale 0 – {series.max ? series.format(series.max) : '—'}</span>
        <span>{formatDay(trend[trend.length - 1]?.start)}</span>
      </div>
    </figure>
  );
}

/**
 * Every bucket as a row, newest first — the charts' data.
 *
 * @param props - The buckets and their length in days.
 * @returns The table.
 */
export function TrendTable({ trend, bucketDays }: { trend: TrendBucket[]; bucketDays: number }) {
  const rows = [...trend].reverse();
  return (
    <div className="ppx__table-wrap">
      <table className="ppx__table" data-testid="phx-trend-table">
        <caption className="sr-only">
          The trend, one row per {bucketDays === 1 ? 'day' : 'week'}, newest first
        </caption>
        <thead>
          <tr>
            <th scope="col">{bucketDays === 1 ? 'Day' : 'Week of'}</th>
            <th scope="col">Runs</th>
            <th scope="col">Failed</th>
            <th scope="col">Pass rate</th>
            <th scope="col">Flips</th>
            <th scope="col">Flakiness</th>
            <th scope="col">Mean duration</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((bucket) => (
            <tr key={bucket.start} className={bucket.metrics.runs ? undefined : 'phx-row--empty'}>
              <th scope="row" className="ppx__mono">
                {formatDay(bucket.start)}
              </th>
              <td className="ppx__mono">{bucket.metrics.runs}</td>
              <td className="ppx__mono">{bucket.metrics.failed}</td>
              <td className="ppx__mono">{formatShare(bucket.metrics.pass_rate)}</td>
              <td className="ppx__mono">{bucket.metrics.flips}</td>
              <td className="ppx__mono">{formatShare(bucket.metrics.flakiness)}</td>
              <td className="ppx__mono">{formatDuration(bucket.metrics.mean_duration_ms)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
