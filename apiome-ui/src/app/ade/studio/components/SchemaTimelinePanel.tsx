'use client';

import * as React from 'react';
import { History, ChevronDown, ChevronUp, X, Loader2, FileDown, GitCompare } from 'lucide-react';
import { cn } from '../../../../../lib/utils';
import { getClassesWithPropertiesAndTagsWithSession } from '../../../../../lib/api/rest-client';
import { computeSchemaMetricsFromClasses } from '@/app/utils/schema-metrics';
import type { SchemaMetricsResult } from '@/app/utils/schema-metrics';
import { downloadSchemaTimelineScoreReportPdf } from '@/app/utils/export-schema-score-report-pdf';
import { buildSchemaScoreCompareRows } from '@/app/utils/schema-version-score-compare';

export interface SchemaTimelineVersion {
  id: string;
  version_id: string;
  description?: string | null;
  published?: boolean;
  created_at?: string;
}

export interface SchemaTimelinePanelProps {
  versions: SchemaTimelineVersion[];
  selectedVersionId: string;
  /** Shown on exported PDF (#252) */
  projectName?: string;
  onSelectVersion?: (versionId: string) => void;
  onClose?: () => void;
  isMinimized?: boolean;
  onMinimizeToggle?: () => void;
}

type TimelinePoint = {
  versionId: string;
  label: string;
  createdAt: string | null;
  metrics: SchemaMetricsResult | null;
  loadError?: string;
};

type TimelinePointWithMetrics = TimelinePoint & { metrics: SchemaMetricsResult };

const CHART_W = 320;
const CHART_H = 120;
const PAD = 8;

function normalizeSeries(values: number[]): number[] {
  if (values.length === 0) return [];
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min;
  if (span <= 0) return values.map(() => CHART_H / 2);
  return values.map((v) => {
    const t = (v - min) / span; // 0 at min, 1 at max
    // Invert for SVG: larger values should be nearer the top (smaller y)
    return PAD + (1 - t) * (CHART_H - 2 * PAD);
  });
}

function buildPolylinePoints(xs: number[], ys: number[]): string {
  return xs.map((x, i) => `${x},${ys[i]}`).join(' ');
}

export default function SchemaTimelinePanel({
  versions,
  selectedVersionId,
  projectName,
  onSelectVersion,
  onClose,
  isMinimized = false,
  onMinimizeToggle,
}: SchemaTimelinePanelProps) {
  const [loading, setLoading] = React.useState(false);
  const [points, setPoints] = React.useState<TimelinePoint[]>([]);
  const [globalError, setGlobalError] = React.useState<string | null>(null);
  const [compareVersionA, setCompareVersionA] = React.useState<string | null>(null);
  const [compareVersionB, setCompareVersionB] = React.useState<string | null>(null);

  const sortedVersions = React.useMemo(() => {
    const copy = [...versions];
    copy.sort((a, b) => {
      const rawA = a.created_at ? Date.parse(a.created_at) : NaN;
      const rawB = b.created_at ? Date.parse(b.created_at) : NaN;
      const ta = Number.isFinite(rawA) ? rawA : 0;
      const tb = Number.isFinite(rawB) ? rawB : 0;
      if (ta !== tb) return ta - tb;
      return (a.version_id || '').localeCompare(b.version_id || '');
    });
    return copy;
  }, [versions]);

  React.useEffect(() => {
    if (sortedVersions.length === 0) {
      setPoints([]);
      setLoading(false);
      return;
    }

    const controller = new AbortController();
    const { signal } = controller;
    setLoading(true);
    setGlobalError(null);

    const run = async () => {
      const next: TimelinePoint[] = [];
      try {
        for (const v of sortedVersions) {
          const res = await getClassesWithPropertiesAndTagsWithSession(v.id, signal);
          if (signal.aborted) return;
          if (!res.success) {
            next.push({
              versionId: v.id,
              label: v.version_id,
              createdAt: v.created_at ?? null,
              metrics: null,
              loadError: res.error || 'Failed to load',
            });
            continue;
          }
          try {
            const metrics = computeSchemaMetricsFromClasses(res.classes || []);
            next.push({
              versionId: v.id,
              label: v.version_id,
              createdAt: v.created_at ?? null,
              metrics,
            });
          } catch (e) {
            next.push({
              versionId: v.id,
              label: v.version_id,
              createdAt: v.created_at ?? null,
              metrics: null,
              loadError: e instanceof Error ? e.message : 'Metrics error',
            });
          }
        }
        if (!signal.aborted) {
          setPoints(next);
          setGlobalError(null);
        }
      } catch (e) {
        if (!signal.aborted) {
          setGlobalError(e instanceof Error ? e.message : 'Failed to load timeline');
        }
      } finally {
        if (!signal.aborted) setLoading(false);
      }
    };

    run();

    return () => {
      controller.abort();
    };
  }, [sortedVersions]);

  const pointsWithMetrics = React.useMemo(
    () =>
      points.filter((p): p is TimelinePointWithMetrics => p.metrics != null && p.loadError == null),
    [points]
  );

  React.useEffect(() => {
    const ok = pointsWithMetrics;
    if (ok.length < 2) {
      setCompareVersionA(null);
      setCompareVersionB(null);
      return;
    }
    setCompareVersionA((prev) => (prev && ok.some((p) => p.versionId === prev) ? prev : ok[0].versionId));
    setCompareVersionB((prev) =>
      prev && ok.some((p) => p.versionId === prev) ? prev : ok[ok.length - 1].versionId
    );
  }, [pointsWithMetrics]);

  const compareRows = React.useMemo(() => {
    if (!compareVersionA || !compareVersionB || compareVersionA === compareVersionB) return null;
    const ma = pointsWithMetrics.find((p) => p.versionId === compareVersionA)?.metrics;
    const mb = pointsWithMetrics.find((p) => p.versionId === compareVersionB)?.metrics;
    if (!ma || !mb) return null;
    return buildSchemaScoreCompareRows(ma, mb);
  }, [compareVersionA, compareVersionB, pointsWithMetrics]);

  const chartData = React.useMemo(() => {
    const ok = points.filter((p) => p.metrics);
    if (ok.length === 0) return null;
    const n = ok.length;
    const xs = ok.map((_, i) => (n === 1 ? CHART_W / 2 : PAD + (i / (n - 1)) * (CHART_W - 2 * PAD)));
    const classes = ok.map((p) => p.metrics!.classCount);
    const rel = ok.map((p) => p.metrics!.relationshipCount);
    const comp = ok.map((p) => p.metrics!.complexityScore);
    return {
      xs,
      yClasses: normalizeSeries(classes),
      yRel: normalizeSeries(rel),
      yComp: normalizeSeries(comp),
      points: ok,
    };
  }, [points]);

  if (isMinimized) {
    return (
      <button
        type="button"
        onClick={onMinimizeToggle}
        className="bg-white/95 dark:bg-gray-800/95 backdrop-blur-sm rounded-xl shadow-lg border border-gray-200/80 dark:border-gray-700/80 px-3 py-2 flex items-center gap-2 text-sm font-medium text-gray-800 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700/80"
        title="Expand schema timeline"
      >
        <History className="w-4 h-4 text-indigo-500 shrink-0" />
        <span>Schema timeline</span>
        <ChevronUp className="w-4 h-4" />
      </button>
    );
  }

  return (
    <div className="bg-white/95 dark:bg-gray-800/95 backdrop-blur-sm rounded-xl shadow-lg border border-gray-200/80 dark:border-gray-700/80 w-[min(100vw-2rem,22rem)] max-h-[min(90vh,32rem)] flex flex-col overflow-hidden">
      <div className="flex items-center justify-between gap-2 px-3 py-2 border-b border-gray-200/80 dark:border-gray-700/80 shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <History className="w-4 h-4 text-indigo-500 shrink-0" />
          <span className="text-sm font-semibold text-gray-800 dark:text-gray-200 truncate">Schema timeline</span>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <button
            type="button"
            onClick={() =>
              downloadSchemaTimelineScoreReportPdf({
                projectName,
                rows: points.map((p) => ({
                  versionLabel: p.label,
                  createdAt: p.createdAt,
                  metrics: p.metrics,
                  loadError: p.loadError,
                })),
              })
            }
            disabled={loading || points.length === 0}
            className="p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-500 disabled:opacity-40 disabled:pointer-events-none"
            title="Export version history as PDF"
            aria-label="Export version history as PDF"
          >
            <FileDown className="w-4 h-4" />
          </button>
          {onMinimizeToggle && (
            <button
              type="button"
              onClick={onMinimizeToggle}
              className="p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-500"
              title="Minimize"
            >
              <ChevronDown className="w-4 h-4" />
            </button>
          )}
          {onClose && (
            <button
              type="button"
              onClick={onClose}
              className="p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-500"
              title="Close"
            >
              <X className="w-4 h-4" />
            </button>
          )}
        </div>
      </div>

      <div className="p-3 overflow-y-auto flex-1 min-h-0 space-y-3">
        <p className="text-xs text-gray-500 dark:text-gray-400">
          Schema size and complexity across each version of this project (oldest → newest).
        </p>

        {loading && (
          <div className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-300">
            <Loader2 className="w-4 h-4 animate-spin text-indigo-500" />
            Loading versions…
          </div>
        )}

        {globalError && (
          <p className="text-sm text-rose-600 dark:text-rose-400">{globalError}</p>
        )}

        {!loading && sortedVersions.length === 0 && (
          <p className="text-sm text-gray-500 dark:text-gray-400">Select a project with versions.</p>
        )}

        {!loading && chartData && chartData.points.length > 0 && (
          <div className="rounded-lg border border-gray-200/80 dark:border-gray-700/80 bg-gray-50/80 dark:bg-gray-900/40 p-2">
            <svg
              viewBox={`0 0 ${CHART_W} ${CHART_H}`}
              className="w-full h-auto text-gray-900 dark:text-gray-100"
              role="img"
              aria-label="Schema metrics over versions"
            >
              <polyline
                fill="none"
                stroke="currentColor"
                className="text-indigo-500"
                strokeWidth="2"
                strokeLinejoin="round"
                strokeLinecap="round"
                points={buildPolylinePoints(chartData.xs, chartData.yClasses)}
              />
              <polyline
                fill="none"
                stroke="currentColor"
                className="text-violet-500"
                strokeWidth="2"
                strokeLinejoin="round"
                strokeLinecap="round"
                points={buildPolylinePoints(chartData.xs, chartData.yRel)}
              />
              <polyline
                fill="none"
                stroke="currentColor"
                className="text-amber-500"
                strokeWidth="2"
                strokeLinejoin="round"
                strokeLinecap="round"
                points={buildPolylinePoints(chartData.xs, chartData.yComp)}
              />
            </svg>
            <div className="flex flex-wrap gap-x-3 gap-y-1 mt-2 text-[10px] text-gray-600 dark:text-gray-400">
              <span className="inline-flex items-center gap-1">
                <span className="inline-block w-2 h-2 rounded-full bg-indigo-500" />
                Classes
              </span>
              <span className="inline-flex items-center gap-1">
                <span className="inline-block w-2 h-2 rounded-full bg-violet-500" />
                Relationships
              </span>
              <span className="inline-flex items-center gap-1">
                <span className="inline-block w-2 h-2 rounded-full bg-amber-500" />
                Complexity
              </span>
            </div>
          </div>
        )}

        {!loading && pointsWithMetrics.length >= 2 && (
          <details className="rounded-lg border border-gray-200/80 dark:border-gray-700/80 bg-gray-50/80 dark:bg-gray-900/40 px-2 py-2">
            <summary className="cursor-pointer flex items-center gap-1.5 text-xs font-medium text-gray-800 dark:text-gray-200 select-none">
              <GitCompare className="w-3.5 h-3.5 text-indigo-500 shrink-0" />
              Compare schema scores
            </summary>
            <div className="mt-2 space-y-2 pt-1 border-t border-gray-200/80 dark:border-gray-700/80">
              <p className="text-[10px] text-gray-500 dark:text-gray-400">
                Pick two versions. Δ is the change from the first selection to the second (second minus first).
              </p>
              <div className="grid grid-cols-1 gap-2">
                <label className="block text-[10px] font-medium text-gray-600 dark:text-gray-300">
                  First version
                  <select
                    className="mt-0.5 w-full rounded-md border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 text-xs px-2 py-1"
                    value={compareVersionA ?? ''}
                    onChange={(e) => setCompareVersionA(e.target.value || null)}
                  >
                    {pointsWithMetrics.map((p) => (
                      <option key={p.versionId} value={p.versionId}>
                        v{p.label}
                        {p.createdAt && Number.isFinite(Date.parse(p.createdAt))
                          ? ` · ${new Date(p.createdAt).toLocaleDateString()}`
                          : ''}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="block text-[10px] font-medium text-gray-600 dark:text-gray-300">
                  Second version
                  <select
                    className="mt-0.5 w-full rounded-md border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 text-xs px-2 py-1"
                    value={compareVersionB ?? ''}
                    onChange={(e) => setCompareVersionB(e.target.value || null)}
                  >
                    {pointsWithMetrics.map((p) => (
                      <option key={`b-${p.versionId}`} value={p.versionId}>
                        v{p.label}
                        {p.createdAt && Number.isFinite(Date.parse(p.createdAt))
                          ? ` · ${new Date(p.createdAt).toLocaleDateString()}`
                          : ''}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              {compareVersionA && compareVersionB && compareVersionA === compareVersionB && (
                <p className="text-[10px] text-amber-700 dark:text-amber-300">Choose two different versions to compare.</p>
              )}
              {compareRows && (
                <div className="overflow-x-auto">
                  <table className="w-full text-[10px] text-left border-collapse">
                    <thead>
                      <tr className="text-gray-500 dark:text-gray-400 border-b border-gray-200/80 dark:border-gray-700/80">
                        <th className="py-1 pr-2 font-medium">Metric</th>
                        <th className="py-1 pr-2 font-medium tabular-nums">First</th>
                        <th className="py-1 pr-2 font-medium tabular-nums">Second</th>
                        <th className="py-1 font-medium tabular-nums">Δ</th>
                      </tr>
                    </thead>
                    <tbody>
                      {compareRows.map((row) => (
                        <tr key={row.label} className="border-b border-gray-100/80 dark:border-gray-800/80">
                          <td className="py-1 pr-2 text-gray-700 dark:text-gray-200">{row.label}</td>
                          <td className="py-1 pr-2 tabular-nums text-gray-600 dark:text-gray-300">{row.valueA}</td>
                          <td className="py-1 pr-2 tabular-nums text-gray-600 dark:text-gray-300">{row.valueB}</td>
                          <td
                            className={cn(
                              'py-1 tabular-nums',
                              row.deltaTone === 'positive' && 'text-emerald-600 dark:text-emerald-400',
                              row.deltaTone === 'negative' && 'text-rose-600 dark:text-rose-400',
                              row.deltaTone === 'neutral' && 'text-gray-600 dark:text-gray-400'
                            )}
                          >
                            {row.delta}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </details>
        )}

        <ul className="space-y-1.5 text-xs">
          {points.map((p) => {
            const isSelected = p.versionId === selectedVersionId;
            const m = p.metrics;
            return (
              <li key={p.versionId}>
                <button
                  type="button"
                  disabled={!onSelectVersion}
                  onClick={() => onSelectVersion?.(p.versionId)}
                  className={cn(
                    'w-full text-left rounded-lg px-2 py-1.5 border transition-colors',
                    isSelected
                      ? 'border-indigo-300 dark:border-indigo-600 bg-indigo-50/90 dark:bg-indigo-950/40'
                      : 'border-transparent hover:bg-gray-100 dark:hover:bg-gray-700/60',
                    onSelectVersion && 'cursor-pointer'
                  )}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium text-gray-800 dark:text-gray-200 truncate">
                      v{p.label}
                      {p.createdAt && Number.isFinite(Date.parse(p.createdAt)) && (
                        <span className="font-normal text-gray-500 dark:text-gray-400 ml-1">
                          · {new Date(p.createdAt).toLocaleDateString()}
                        </span>
                      )}
                    </span>
                  </div>
                  {p.loadError && (
                    <span className="text-rose-600 dark:text-rose-400">{p.loadError}</span>
                  )}
                  {m && !p.loadError && (
                    <div className="text-gray-500 dark:text-gray-400 mt-0.5 tabular-nums">
                      {m.classCount} classes · {m.relationshipCount} rel · complexity {m.complexityScore}{' '}
                      <span
                        className={cn(
                          m.complexityLabel === 'Low' && 'text-emerald-600 dark:text-emerald-400',
                          m.complexityLabel === 'Medium' && 'text-amber-600 dark:text-amber-400',
                          m.complexityLabel === 'High' && 'text-rose-600 dark:text-rose-400'
                        )}
                      >
                        ({m.complexityLabel})
                      </span>
                    </div>
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}
