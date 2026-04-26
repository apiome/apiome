'use client';

/**
 * Quality + Lint side-by-side scorecards for the version detail page.
 *
 * Both panels are dumb: the parent runs the fetch + run-trigger and pumps
 * the latest snapshot/result + a state machine into props, so this file
 * stays free of fetch logic and is easy to render in tests with synthetic
 * data. Each card has three states:
 *
 *   - `loading`    — waiting on the initial GET, render a skeleton.
 *   - `empty`      — no snapshot/result on file, render the CTA button.
 *   - `populated`  — render the score + delta-vs-previous, with a small
 *                    "re-run" affordance to refresh the snapshot.
 *
 * The structural shape mirrors `mockups/versions/version.html` (circle
 * gauge + four sub-bars on the quality side, big grade letter + counters
 * on the lint side).
 */

import { useMemo } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  Gauge,
  Info,
  Loader2,
  Play,
  TrendingDown,
  TrendingUp,
  XCircle,
} from 'lucide-react';
import { relativeTime } from '../projectDetail/versionsTab/versionLifecycle';

export interface QualitySnapshot {
  id: string;
  tenant_id: string;
  project_id: string;
  version_id: string;
  overall: number;
  completeness: number;
  consistency: number;
  descriptions: number;
  examples: number;
  class_count: number;
  property_count: number;
  computed_by?: string | null;
  computed_at?: string | null;
  detail?: Record<string, unknown> | null;
}

export interface LintResult {
  id: string;
  tenant_id: string;
  project_id: string;
  version_id: string;
  grade: 'A' | 'B' | 'C' | 'D' | 'F';
  error_count: number;
  warning_count: number;
  info_count: number;
  rules_applied: number;
  duration_ms?: number | null;
  computed_by?: string | null;
  computed_at?: string | null;
  detail?: Record<string, unknown> | null;
}

export interface LintFinding {
  id: string;
  result_id: string;
  version_id: string;
  rule_id: string;
  severity: 'error' | 'warning' | 'info';
  target_kind: 'class' | 'property' | 'schema';
  target_id?: string | null;
  target_path: string;
  message: string;
  suggestion?: string | null;
  detail?: Record<string, unknown> | null;
  created_at?: string | null;
}

export type PanelState = 'loading' | 'idle' | 'busy' | 'error';

export interface QualityLintPanelsProps {
  quality: QualitySnapshot | null;
  qualityPrevious: QualitySnapshot | null;
  qualityState: PanelState;
  qualityError: string | null;
  onComputeQuality: () => void;

  lint: LintResult | null;
  lintFindings: LintFinding[];
  lintPrevious: LintResult | null;
  lintState: PanelState;
  lintError: string | null;
  onRunLint: () => void;
}

export function QualityLintPanels(props: QualityLintPanelsProps) {
  return (
    <section className="grid grid-cols-1 md:grid-cols-2 gap-4">
      <QualityCard
        quality={props.quality}
        previous={props.qualityPrevious}
        state={props.qualityState}
        error={props.qualityError}
        onCompute={props.onComputeQuality}
      />
      <LintCard
        result={props.lint}
        findings={props.lintFindings}
        previous={props.lintPrevious}
        state={props.lintState}
        error={props.lintError}
        onRun={props.onRunLint}
      />
    </section>
  );
}

/* ---------- Quality card ---------- */

interface QualityCardProps {
  quality: QualitySnapshot | null;
  previous: QualitySnapshot | null;
  state: PanelState;
  error: string | null;
  onCompute: () => void;
}

function QualityCard({ quality, previous, state, error, onCompute }: QualityCardProps) {
  return (
    <article className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-5">
      <header className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Gauge className="w-4 h-4 text-emerald-500" aria-hidden="true" />
          <h3 className="text-sm font-semibold">Quality</h3>
        </div>
        {quality?.computed_at ? (
          <span className="text-[10px] font-mono text-gray-400">
            computed {relativeTime(quality.computed_at)}
          </span>
        ) : null}
      </header>

      {state === 'loading' ? (
        <SkeletonRow />
      ) : !quality ? (
        <EmptyPanel
          message="This version has no quality snapshot yet."
          actionLabel={state === 'busy' ? 'Computing…' : 'Compute quality'}
          actionDisabled={state === 'busy'}
          onAction={onCompute}
          actionIcon={
            state === 'busy' ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Play className="w-4 h-4" />
            )
          }
        />
      ) : (
        <>
          <div className="flex items-center gap-5">
            <ScoreGauge value={quality.overall} />
            <div className="flex-1 space-y-2.5">
              <SubScoreBar label="Completeness" value={quality.completeness} />
              <SubScoreBar label="Consistency" value={quality.consistency} />
              <SubScoreBar label="Descriptions" value={quality.descriptions} />
              <SubScoreBar label="Examples" value={quality.examples} />
            </div>
          </div>

          <footer className="mt-4 pt-3 border-t border-gray-100 dark:border-gray-700/60 flex items-center justify-between text-[11px]">
            <span className="text-gray-500 dark:text-gray-400 font-mono">
              {quality.class_count} class{quality.class_count === 1 ? '' : 'es'} ·{' '}
              {quality.property_count} prop{quality.property_count === 1 ? '' : 's'}
            </span>
            <div className="flex items-center gap-2">
              {previous ? <Delta current={quality.overall} prior={previous.overall} /> : null}
              <button
                type="button"
                onClick={onCompute}
                disabled={state === 'busy'}
                className="text-[10px] font-mono text-indigo-500 hover:underline inline-flex items-center gap-1 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {state === 'busy' ? (
                  <Loader2 className="w-3 h-3 animate-spin" aria-hidden="true" />
                ) : (
                  <Play className="w-3 h-3" aria-hidden="true" />
                )}
                {state === 'busy' ? 're-running…' : 're-run'}
              </button>
            </div>
          </footer>
        </>
      )}

      {error ? (
        <p className="mt-3 text-[11px] text-rose-600 dark:text-rose-400" role="alert">
          {error}
        </p>
      ) : null}
    </article>
  );
}

/* ---------- Lint card ---------- */

interface LintCardProps {
  result: LintResult | null;
  findings: LintFinding[];
  previous: LintResult | null;
  state: PanelState;
  error: string | null;
  onRun: () => void;
}

function LintCard({ result, findings, previous, state, error, onRun }: LintCardProps) {
  const severityCounts = useMemo(() => ({
    error: result?.error_count ?? 0,
    warning: result?.warning_count ?? 0,
    info: result?.info_count ?? 0,
  }), [result]);

  /* Top three findings by severity (errors first, then warnings, then info)
     for the in-card preview. The full findings list is reachable via the
     "view all" link to a future /findings sub-route. */
  const previewFindings = useMemo(() => {
    if (findings.length === 0) return [];
    const order: Record<LintFinding['severity'], number> = { error: 0, warning: 1, info: 2 };
    return [...findings]
      .sort((a, b) => order[a.severity] - order[b.severity])
      .slice(0, 3);
  }, [findings]);

  return (
    <article className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-5">
      <header className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <CheckCircle2 className="w-4 h-4 text-emerald-500" aria-hidden="true" />
          <h3 className="text-sm font-semibold">Lint</h3>
        </div>
        {result?.computed_at ? (
          <button
            type="button"
            onClick={onRun}
            disabled={state === 'busy'}
            className="text-[10px] font-mono text-indigo-500 hover:underline inline-flex items-center gap-1 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {state === 'busy' ? (
              <Loader2 className="w-3 h-3 animate-spin" aria-hidden="true" />
            ) : (
              <Play className="w-3 h-3" aria-hidden="true" />
            )}
            {state === 'busy' ? 'running…' : 're-run'}
          </button>
        ) : null}
      </header>

      {state === 'loading' ? (
        <SkeletonRow />
      ) : !result ? (
        <EmptyPanel
          message="This version has never been linted."
          actionLabel={state === 'busy' ? 'Running…' : 'Run lint'}
          actionDisabled={state === 'busy'}
          onAction={onRun}
          actionIcon={
            state === 'busy' ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Play className="w-4 h-4" />
            )
          }
        />
      ) : (
        <>
          <div className="flex items-center gap-5">
            <GradeBadge grade={result.grade} />
            <div className="flex-1 space-y-2 font-mono text-[11px]">
              <SeverityLine kind="error" count={severityCounts.error} />
              <SeverityLine kind="warning" count={severityCounts.warning} />
              <SeverityLine kind="info" count={severityCounts.info} />
            </div>
          </div>

          {previewFindings.length > 0 ? (
            <ul className="mt-4 space-y-2">
              {previewFindings.map((f) => (
                <li key={f.id}>
                  <FindingChip finding={f} />
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-4 text-[11px] text-emerald-600 dark:text-emerald-400">
              No findings — the schema passes every active rule.
            </p>
          )}

          <footer className="mt-3 pt-3 border-t border-gray-100 dark:border-gray-700/60 flex items-center justify-between text-[11px]">
            <span className="text-gray-500 dark:text-gray-400 font-mono">
              {result.rules_applied} rule{result.rules_applied === 1 ? '' : 's'} applied
              {result.duration_ms != null ? ` · ${result.duration_ms} ms` : ''}
            </span>
            <span className="text-gray-500">
              {previous ? (
                <GradeDelta current={result.grade} prior={previous.grade} />
              ) : (
                <span className="font-mono text-gray-400">first run</span>
              )}
            </span>
          </footer>
        </>
      )}

      {error ? (
        <p className="mt-3 text-[11px] text-rose-600 dark:text-rose-400" role="alert">
          {error}
        </p>
      ) : null}
    </article>
  );
}

/* ---------- Atoms ---------- */

function ScoreGauge({ value }: { value: number }) {
  const safeValue = Math.max(0, Math.min(100, Math.round(value)));
  const tone = scoreTone(safeValue);
  const stroke = scoreStroke(safeValue);
  return (
    <div className="relative w-20 h-20 shrink-0">
      <svg viewBox="0 0 36 36" className="w-full h-full -rotate-90">
        <circle
          cx="18"
          cy="18"
          r="15"
          stroke="rgba(148,163,184,0.20)"
          strokeWidth="3"
          fill="none"
        />
        <circle
          cx="18"
          cy="18"
          r="15"
          stroke={stroke}
          strokeWidth="3"
          fill="none"
          strokeDasharray={`${safeValue} 100`}
          strokeLinecap="round"
          pathLength={100}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className={`font-mono font-bold text-xl leading-none ${tone}`}>{safeValue}</span>
        <span className="text-[9px] font-mono text-gray-400 leading-none mt-0.5">/ 100</span>
      </div>
    </div>
  );
}

interface SubScoreBarProps {
  label: string;
  value: number;
}

function SubScoreBar({ label, value }: SubScoreBarProps) {
  const safeValue = Math.max(0, Math.min(100, Math.round(value)));
  const stroke = scoreStroke(safeValue);
  return (
    <div>
      <div className="flex items-center justify-between text-[11px] mb-1">
        <span className="font-medium text-gray-600 dark:text-gray-300">{label}</span>
        <span className="font-mono text-gray-500">{safeValue}</span>
      </div>
      <div
        className="h-1.5 rounded-full bg-slate-200/70 dark:bg-slate-700/60 overflow-hidden"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={safeValue}
        aria-label={`${label} score`}
      >
        <span
          className="block h-full rounded-full"
          style={{ width: `${safeValue}%`, background: stroke }}
        />
      </div>
    </div>
  );
}

function GradeBadge({ grade }: { grade: LintResult['grade'] }) {
  const tone = gradeTone(grade);
  return (
    <div
      className={`w-20 h-20 rounded-md border-2 flex items-center justify-center shrink-0 ${tone.borderClass}`}
    >
      <span className={`font-bold text-3xl font-mono ${tone.textClass}`}>{grade}</span>
    </div>
  );
}

interface SeverityLineProps {
  kind: 'error' | 'warning' | 'info';
  count: number;
}

function SeverityLine({ kind, count }: SeverityLineProps) {
  const meta = severityMeta(kind);
  return (
    <div className="flex items-center justify-between">
      <span className="inline-flex items-center gap-1.5 text-gray-600 dark:text-gray-300">
        <span className={`w-2 h-2 rounded-full ${meta.dotClass}`} aria-hidden="true" />
        {meta.label}
      </span>
      <span className={`font-semibold ${count > 0 ? meta.textClass : 'text-gray-400'}`}>
        {count}
      </span>
    </div>
  );
}

function FindingChip({ finding }: { finding: LintFinding }) {
  const meta = severityMeta(finding.severity);
  const Icon = meta.icon;
  return (
    <div
      className={`flex items-start gap-2 text-[11px] p-2 rounded border ${meta.chipClass}`}
    >
      <Icon className={`w-3.5 h-3.5 mt-0.5 shrink-0 ${meta.iconClass}`} aria-hidden="true" />
      <div className="flex-1 min-w-0">
        <p className="text-gray-700 dark:text-gray-200 truncate">{finding.message}</p>
        <p className="font-mono text-[10px] text-gray-500 truncate" title={finding.target_path}>
          {finding.target_path} · rule <code>{finding.rule_id}</code>
        </p>
      </div>
    </div>
  );
}

interface DeltaProps {
  current: number;
  prior: number;
}

function Delta({ current, prior }: DeltaProps) {
  const diff = current - prior;
  if (diff === 0) {
    return <span className="font-mono text-gray-500">no change</span>;
  }
  const Icon = diff > 0 ? TrendingUp : TrendingDown;
  const tone = diff > 0 ? 'text-emerald-500' : 'text-rose-500';
  return (
    <span className={`inline-flex items-center gap-1 font-mono font-semibold ${tone}`}>
      <Icon className="w-3 h-3" aria-hidden="true" />
      {diff > 0 ? '+' : ''}
      {diff} pts
    </span>
  );
}

const GRADE_RANK: Record<LintResult['grade'], number> = { A: 4, B: 3, C: 2, D: 1, F: 0 };

function GradeDelta({
  current,
  prior,
}: {
  current: LintResult['grade'];
  prior: LintResult['grade'];
}) {
  const cur = GRADE_RANK[current];
  const pri = GRADE_RANK[prior];
  if (cur === pri) {
    return <span className="font-mono text-gray-500">grade unchanged</span>;
  }
  const Icon = cur > pri ? TrendingUp : TrendingDown;
  const tone = cur > pri ? 'text-emerald-500' : 'text-rose-500';
  return (
    <span className={`inline-flex items-center gap-1 font-mono font-semibold ${tone}`}>
      <Icon className="w-3 h-3" aria-hidden="true" />
      {prior} → {current}
    </span>
  );
}

interface EmptyPanelProps {
  message: string;
  actionLabel: string;
  actionDisabled: boolean;
  onAction: () => void;
  actionIcon: React.ReactNode;
}

function EmptyPanel({
  message,
  actionLabel,
  actionDisabled,
  onAction,
  actionIcon,
}: EmptyPanelProps) {
  return (
    <div className="flex flex-col items-start gap-3 py-4">
      <p className="text-xs text-gray-500 dark:text-gray-400">{message}</p>
      <button
        type="button"
        onClick={onAction}
        disabled={actionDisabled}
        className="px-3 py-1.5 text-sm rounded-md bg-indigo-600 hover:bg-indigo-700 text-white inline-flex items-center gap-2 disabled:opacity-60 disabled:cursor-not-allowed"
      >
        {actionIcon}
        {actionLabel}
      </button>
    </div>
  );
}

function SkeletonRow() {
  return (
    <div className="flex items-center gap-5 animate-pulse">
      <div className="w-20 h-20 rounded-md bg-gray-100 dark:bg-gray-700/60" />
      <div className="flex-1 space-y-2">
        <div className="h-2 w-3/5 rounded bg-gray-100 dark:bg-gray-700/60" />
        <div className="h-2 w-2/5 rounded bg-gray-100 dark:bg-gray-700/60" />
        <div className="h-2 w-3/4 rounded bg-gray-100 dark:bg-gray-700/60" />
        <div className="h-2 w-1/2 rounded bg-gray-100 dark:bg-gray-700/60" />
      </div>
    </div>
  );
}

/* ---------- Tones ---------- */

function scoreTone(value: number): string {
  if (value >= 85) return 'text-emerald-600 dark:text-emerald-400';
  if (value >= 70) return 'text-indigo-600 dark:text-indigo-400';
  if (value >= 50) return 'text-amber-600 dark:text-amber-400';
  return 'text-rose-600 dark:text-rose-400';
}

function scoreStroke(value: number): string {
  if (value >= 85) return '#10b981';
  if (value >= 70) return '#6366f1';
  if (value >= 50) return '#f59e0b';
  return '#f43f5e';
}

function gradeTone(grade: LintResult['grade']): { borderClass: string; textClass: string } {
  switch (grade) {
    case 'A':
      return {
        borderClass: 'border-emerald-500',
        textClass: 'text-emerald-600 dark:text-emerald-400',
      };
    case 'B':
      return {
        borderClass: 'border-indigo-500',
        textClass: 'text-indigo-600 dark:text-indigo-400',
      };
    case 'C':
      return {
        borderClass: 'border-amber-500',
        textClass: 'text-amber-600 dark:text-amber-400',
      };
    case 'D':
      return {
        borderClass: 'border-orange-500',
        textClass: 'text-orange-600 dark:text-orange-400',
      };
    case 'F':
      return {
        borderClass: 'border-rose-500',
        textClass: 'text-rose-600 dark:text-rose-400',
      };
  }
}

interface SeverityMeta {
  label: string;
  dotClass: string;
  textClass: string;
  iconClass: string;
  chipClass: string;
  icon: typeof XCircle;
}

function severityMeta(kind: LintFinding['severity']): SeverityMeta {
  switch (kind) {
    case 'error':
      return {
        label: 'Errors',
        dotClass: 'bg-rose-500',
        textClass: 'text-rose-500',
        iconClass: 'text-rose-500',
        chipClass:
          'border-rose-200 dark:border-rose-700/40 bg-rose-50/60 dark:bg-rose-900/15',
        icon: XCircle,
      };
    case 'warning':
      return {
        label: 'Warnings',
        dotClass: 'bg-amber-500',
        textClass: 'text-amber-500',
        iconClass: 'text-amber-500',
        chipClass:
          'border-amber-200 dark:border-amber-700/40 bg-amber-50/60 dark:bg-amber-900/15',
        icon: AlertTriangle,
      };
    case 'info':
      return {
        label: 'Info',
        dotClass: 'bg-sky-500',
        textClass: 'text-sky-500',
        iconClass: 'text-sky-500',
        chipClass:
          'border-sky-200 dark:border-sky-700/40 bg-sky-50/60 dark:bg-sky-900/15',
        icon: Info,
      };
  }
}
