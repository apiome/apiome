'use client';

import * as React from 'react';
import { Gauge, Loader2, X, ChevronDown, ChevronUp } from 'lucide-react';
import { cn } from '../../../../../lib/utils';
import { easeOutCubic } from '../../../../../lib/animation-easing';
import { getClassesWithPropertiesAndTagsWithSession } from '../../../../../lib/api/rest-client';
import { computePerSchemaScoresFromClasses } from '@/app/utils/schema-metrics';
import { getNumericScoreTier } from '@/app/utils/numeric-score-tier';
import type { PerSchemaScoreRow } from '@/app/utils/schema-metrics';
import type { Version } from '../editor/components/types';

export type SchemaVersionScoringVersion = Pick<
  Version,
  'id' | 'version_id' | 'description' | 'published' | 'created_at'
>;

export interface SchemaVersionScoringPanelProps {
  versions: SchemaVersionScoringVersion[];
  selectedVersionId: string;
  onSelectVersion?: (versionId: string) => void;
  onClose?: () => void;
  isMinimized?: boolean;
  onMinimizeToggle?: () => void;
  /** Studio version id for the open canvas; when it matches the breakdown version, scores use the live graph (#244). */
  liveCanvasVersionId?: string | null;
  /** Per-class scores from current canvas nodes/edges; paired with `liveCanvasVersionId`. */
  livePerSchemaRows?: PerSchemaScoreRow[];
}

const GAUGE_R = 16;
const GAUGE_C = 2 * Math.PI * GAUGE_R;
const GAUGE_ANIMATION_MS = 750;

function AnimatedScoreGauge({
  value,
  label,
  variant,
  animationKey,
}: {
  value: number;
  label: string;
  variant: 'higher-better' | 'complexity';
  /** Bump to re-run mount animation */
  animationKey: string;
}) {
  const arcRef = React.useRef<SVGCircleElement>(null);
  const textRef = React.useRef<HTMLSpanElement>(null);

  const target = Math.min(100, Math.max(0, value));

  // Compute stroke color class from the final target value so it never
  // changes during the animation (avoids class-swap thrash on every tick).
  const strokeClass =
    variant === 'complexity'
      ? target <= 33
        ? 'text-emerald-500'
        : target <= 66
          ? 'text-amber-500'
          : 'text-rose-500'
      : getNumericScoreTier(target).gaugeStrokeClass;

  React.useEffect(() => {
    const arc = arcRef.current;
    const text = textRef.current;
    if (!arc || !text) return;

    let cancelled = false;

    if (typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      arc.style.strokeDashoffset = String(GAUGE_C * (1 - target / 100));
      text.textContent = String(Math.round(target));
      return;
    }

    // Reset to 0 imperatively – no React state, no re-render.
    arc.style.strokeDashoffset = String(GAUGE_C);
    text.textContent = '0';

    let start: number | null = null;
    let raf = 0;

    const step = (now: number) => {
      if (cancelled) return;
      if (start === null) start = now;
      const elapsed = now - start;
      const t = Math.min(1, elapsed / GAUGE_ANIMATION_MS);
      const eased = easeOutCubic(t);
      const displayValue = eased * target;
      arc.style.strokeDashoffset = String(GAUGE_C * (1 - displayValue / 100));
      text.textContent = String(Math.round(displayValue));
      if (t < 1) {
        raf = window.requestAnimationFrame(step);
      }
    };

    raf = window.requestAnimationFrame(step);

    return () => {
      cancelled = true;
      window.cancelAnimationFrame(raf);
    };
  }, [target, animationKey]);

  return (
    <div className="flex flex-col items-center gap-0.5 min-w-0">
      <div className="relative w-11 h-11 shrink-0">
        <svg viewBox="0 0 40 40" className="w-full h-full -rotate-90" aria-hidden>
          <circle
            cx="20"
            cy="20"
            r={GAUGE_R}
            fill="none"
            className="stroke-gray-200 dark:stroke-gray-600"
            strokeWidth="4"
          />
          <circle
            ref={arcRef}
            cx="20"
            cy="20"
            r={GAUGE_R}
            fill="none"
            className={cn('stroke-current', strokeClass)}
            strokeWidth="4"
            strokeLinecap="round"
            strokeDasharray={GAUGE_C}
            strokeDashoffset={GAUGE_C}
          />
        </svg>
        <span
          ref={textRef}
          className="absolute inset-0 z-10 flex items-center justify-center text-[9px] font-semibold text-gray-800 dark:text-gray-100 tabular-nums pointer-events-none"
        >
          0
        </span>
      </div>
      <span className="text-[9px] text-center text-gray-500 dark:text-gray-400 leading-tight max-w-[4.5rem] truncate" title={label}>
        {label}
      </span>
    </div>
  );
}

export default function SchemaVersionScoringPanel({
  versions,
  selectedVersionId,
  onSelectVersion,
  onClose,
  isMinimized = false,
  onMinimizeToggle,
  liveCanvasVersionId = null,
  livePerSchemaRows = [],
}: SchemaVersionScoringPanelProps) {
  const [breakdownVersionId, setBreakdownVersionId] = React.useState(selectedVersionId);
  const [loading, setLoading] = React.useState(false);
  const [rows, setRows] = React.useState<PerSchemaScoreRow[]>([]);
  const [error, setError] = React.useState<string | null>(null);
  const [animTick, setAnimTick] = React.useState(0);

  const useLiveCanvasScores = Boolean(
    breakdownVersionId && liveCanvasVersionId && breakdownVersionId === liveCanvasVersionId
  );

  const displayRows = useLiveCanvasScores ? livePerSchemaRows : rows;

  React.useEffect(() => {
    setBreakdownVersionId(selectedVersionId);
  }, [selectedVersionId]);

  React.useEffect(() => {
    if (!breakdownVersionId) {
      setRows([]);
      setError(null);
      setLoading(false);
      return;
    }

    if (useLiveCanvasScores) {
      setError(null);
      setLoading(false);
      return;
    }

    const controller = new AbortController();
    const { signal } = controller;
    setLoading(true);
    setError(null);

    getClassesWithPropertiesAndTagsWithSession(breakdownVersionId, signal)
      .then((res) => {
        if (signal.aborted) return;
        if (!res.success) {
          setRows([]);
          setError(res.error || 'Failed to load classes');
          return;
        }
        try {
          const next = computePerSchemaScoresFromClasses(res.classes || []);
          setRows(next);
          setAnimTick((t) => t + 1);
        } catch (e) {
          setRows([]);
          setError(e instanceof Error ? e.message : 'Failed to compute scores');
        }
      })
      .catch(() => {
        if (!signal.aborted) {
          setRows([]);
          setError('Failed to load classes');
        }
      })
      .finally(() => {
        if (!signal.aborted) setLoading(false);
      });

    return () => controller.abort();
  }, [breakdownVersionId, useLiveCanvasScores]);

  const sortedVersions = React.useMemo(() => {
    const copy = [...versions];
    copy.sort((a, b) => {
      const rawA = a.created_at ? Date.parse(a.created_at) : NaN;
      const rawB = b.created_at ? Date.parse(b.created_at) : NaN;
      const ta = Number.isFinite(rawA) ? rawA : 0;
      const tb = Number.isFinite(rawB) ? rawB : 0;
      if (ta !== tb) return tb - ta;
      return (b.version_id || '').localeCompare(a.version_id || '');
    });
    return copy;
  }, [versions]);

  if (isMinimized) {
    return (
      <button
        type="button"
        onClick={() => onMinimizeToggle?.()}
        disabled={!onMinimizeToggle}
        className="bg-white/95 dark:bg-gray-800/95 backdrop-blur-sm rounded-xl shadow-lg border border-gray-200/80 dark:border-gray-700/80 px-3 py-2 flex items-center gap-2 text-sm font-medium text-gray-800 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700/80 disabled:cursor-default"
        title="Expand version scoring"
      >
        <Gauge className="w-4 h-4 text-indigo-500 shrink-0" />
        <span>Version scoring</span>
        <ChevronUp className="w-4 h-4" />
      </button>
    );
  }

  return (
    <div className="bg-white/95 dark:bg-gray-800/95 backdrop-blur-sm rounded-xl shadow-lg border border-gray-200/80 dark:border-gray-700/80 w-[min(calc(100vw_-_2rem),_24rem)] max-h-[min(90vh,36rem)] flex flex-col overflow-hidden">
      <div className="flex items-center justify-between gap-2 px-3 py-2 border-b border-gray-200/80 dark:border-gray-700/80 shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <Gauge className="w-4 h-4 text-indigo-500 shrink-0" />
          <span className="text-sm font-semibold text-gray-800 dark:text-gray-200 truncate">Version scoring</span>
        </div>
        <div className="flex items-center gap-1 shrink-0">
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
            <button type="button" onClick={onClose} className="p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-500" title="Close">
              <X className="w-4 h-4" />
            </button>
          )}
        </div>
      </div>

      <div className="p-3 overflow-y-auto flex-1 min-h-0 space-y-3">
        <p className="text-xs text-gray-500 dark:text-gray-400">
          Pick a project version to see documentation, naming, and complexity scores per schema (class), with animated gauges.
        </p>
        {useLiveCanvasScores && (
          <p className="text-xs text-emerald-700 dark:text-emerald-400/90">
            Live — scores follow the current canvas for this version as you edit.
          </p>
        )}

        <label className="block text-[10px] font-medium text-gray-600 dark:text-gray-300">
          Version
          <select
            className="mt-0.5 w-full rounded-md border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 text-xs px-2 py-1.5"
            value={breakdownVersionId}
            onChange={(e) => {
              setBreakdownVersionId(e.target.value);
            }}
          >
            <option value="">Select version…</option>
            {sortedVersions.map((v) => (
              <option key={v.id} value={v.id}>
                v{v.version_id}
                {v.created_at && Number.isFinite(Date.parse(v.created_at)) ? ` · ${new Date(v.created_at).toLocaleDateString()}` : ''}
              </option>
            ))}
          </select>
        </label>

        {loading && (
          <div className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-300">
            <Loader2 className="w-4 h-4 animate-spin text-indigo-500" />
            Loading schemas…
          </div>
        )}

        {error && <p className="text-sm text-rose-600 dark:text-rose-400">{error}</p>}

        {!loading && breakdownVersionId && displayRows.length === 0 && !error && (
          <p className="text-sm text-gray-500 dark:text-gray-400">No classes in this version.</p>
        )}

        <ul className="space-y-2">
          {displayRows.map((row) => (
            <li
              key={row.classId}
              className="rounded-lg border border-gray-200/80 dark:border-gray-700/80 bg-gray-50/80 dark:bg-gray-900/40 px-2 py-2"
            >
              <div className="text-xs font-medium text-gray-800 dark:text-gray-100 truncate mb-1.5" title={row.className}>
                {row.className}
              </div>
              <div className="flex justify-around gap-1">
                <AnimatedScoreGauge
                  value={row.documentationScore}
                  label="Docs"
                  variant="higher-better"
                  animationKey={`${animTick}-${row.classId}-doc`}
                />
                <AnimatedScoreGauge
                  value={row.namingScore}
                  label="Naming"
                  variant="higher-better"
                  animationKey={`${animTick}-${row.classId}-name`}
                />
                <AnimatedScoreGauge
                  value={row.complexityScore}
                  label={`Complexity (${row.complexityLabel})`}
                  variant="complexity"
                  animationKey={`${animTick}-${row.classId}-cx`}
                />
              </div>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
