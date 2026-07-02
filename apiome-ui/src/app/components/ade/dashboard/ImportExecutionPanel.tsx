'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import * as Progress from '@radix-ui/react-progress';
import { Button } from '../../../components/ui/Button';
import { Badge } from '../../../components/ui/Badge';
import {
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  Circle,
  Info,
  Loader2,
  XCircle,
  RotateCw,
  MinusCircle,
} from 'lucide-react';
import { cancelImport, getImportStatus, commitImport, rollbackImport, retryImport } from '../../../../../lib/db/import-actions';
import {
  getErrorEvents,
  formatEventContext,
  getLiveProgressRowClasses,
  getImportLogLineClasses,
  isSkippedEvent,
} from '../../../../../lib/import-execution-error-indicators';
import {
  buildImportLiveChecklist,
  formatProgressPrimaryLine,
  estimateSecondsRemaining,
} from '../../../../../lib/import-execution-live-rows';

interface ImportExecutionPanelProps {
  jobId: string;
  /** Schema names selected on the Preview step — drives the live checklist (#296). */
  selectedSchemas?: string[];
  onComplete?: (succeeded: boolean) => void;
  /** When user retries a failed/canceled import, called with the new job ID so the dialog can switch to it. */
  onRetry?: (newJobId: string) => void;
  isReviewing?: boolean; // True when viewing from 'done' step via Back button
}

type LogLevel = 'info' | 'warn' | 'error';

interface ImportEvent {
  id: string;
  ts: number;
  level: LogLevel;
  code: string;
  message: string;
  context?: unknown;
}

interface ProgressInfo {
  phase:
    | 'initializing'
    | 'creating-project'
    | 'creating-version'
    | 'creating-properties'
    | 'creating-classes'
    | 'linking-properties'
    | 'verifying'
    | 'finalizing';
  total: number;
  completed: number;
  currentItem?: string;
}

type JobState = 'queued' | 'running' | 'pending-approval' | 'committing' | 'completed' | 'failed' | 'canceled' | 'rolled-back';

const IMPORT_LOG_PREVIEW_COUNT = 8;

function formatEtaLine(seconds: number | null): string | null {
  if (seconds == null) return null;
  if (seconds < 60) {
    return seconds === 1
      ? 'Estimated time remaining: about 1 second'
      : `Estimated time remaining: about ${seconds} seconds`;
  }
  const m = Math.max(1, Math.round(seconds / 60));
  return m === 1 ? 'Estimated time remaining: about 1 minute' : `Estimated time remaining: about ${m} minutes`;
}

export default function ImportExecutionPanel({
  jobId,
  selectedSchemas = [],
  onComplete,
  onRetry,
  isReviewing,
}: ImportExecutionPanelProps) {
  const [state, setState] = useState<JobState>('queued');
  const [percent, setPercent] = useState(0);
  const [progress, setProgress] = useState<ProgressInfo | undefined>(undefined);
  const [events, setEvents] = useState<ImportEvent[]>([]);
  const [summary, setSummary] = useState<Record<string, unknown> | null>(null);
  const [isCommitting, setIsCommitting] = useState(false);
  const [isRollingBack, setIsRollingBack] = useState(false);
  const [isRetrying, setIsRetrying] = useState(false);
  const [transactionPending, setTransactionPending] = useState(false);
  const [logExpanded, setLogExpanded] = useState(false);
  const importStartedAtMs = useRef<number | null>(null);
  const completionNotifiedRef = useRef(false);

  const liveRows = useMemo(
    () => buildImportLiveChecklist(selectedSchemas, events, progress, state),
    [selectedSchemas, events, progress, state]
  );

  const primaryLine = formatProgressPrimaryLine(progress, state);
  const etaSeconds = estimateSecondsRemaining(
    percent,
    importStartedAtMs.current != null ? Date.now() - importStartedAtMs.current : 0
  );
  const etaLine =
    ['running', 'queued', 'committing'].includes(state) && percent > 0 && percent < 100
      ? formatEtaLine(etaSeconds)
      : null;

  useEffect(() => {
    completionNotifiedRef.current = false;
    importStartedAtMs.current = null;
  }, [jobId]);

  useEffect(() => {
    let mounted = true;
    let timer: ReturnType<typeof setInterval> | undefined;

    const poll = async () => {
      try {
        const status = await getImportStatus(jobId);
        if (!mounted) return;
        if (importStartedAtMs.current === null && ((status.percent ?? 0) > 0 || (status.events?.length ?? 0) > 0)) {
          importStartedAtMs.current = Date.now();
        }
        setState(status.state as JobState);
        setPercent(status.percent || 0);
        setProgress(status.progress as ProgressInfo | undefined);
        setEvents(status.events || []);
        setSummary(status.summary || null);
        setTransactionPending((status as { transactionPending?: boolean }).transactionPending || false);

        if (['completed', 'failed', 'canceled', 'rolled-back', 'pending-approval'].includes(status.state)) {
          if (timer) clearInterval(timer);
          if (!completionNotifiedRef.current && onComplete) {
            completionNotifiedRef.current = true;
            onComplete(status.state === 'completed');
          }
        }
      } catch {
        // Ignore transient errors
      }
    };

    if (isReviewing) {
      poll();
    } else {
      poll();
      timer = setInterval(poll, 1000);
    }

    return () => {
      mounted = false;
      if (timer) clearInterval(timer);
    };
  }, [jobId, onComplete, isReviewing]);

  const onCancel = async () => {
    await cancelImport(jobId);
  };

  const onAccept = async () => {
    setIsCommitting(true);
    try {
      const result = await commitImport(jobId);
      if (result.success) {
        setState('completed');
        if (onComplete) {
          onComplete(true);
        }
      } else {
        const status = await getImportStatus(jobId);
        setState(status.state as JobState);
        setEvents(status.events || []);
      }
    } catch (e) {
      console.error('Failed to commit:', e);
    } finally {
      setIsCommitting(false);
    }
  };

  const onReject = async () => {
    setIsRollingBack(true);
    try {
      await rollbackImport(jobId);
      setState('rolled-back');
      if (onComplete) {
        onComplete(false);
      }
    } catch (e) {
      console.error('Failed to rollback:', e);
    } finally {
      setIsRollingBack(false);
    }
  };

  const onRetryClick = async () => {
    if (!onRetry) return;
    setIsRetrying(true);
    try {
      const result = await retryImport(jobId);
      if (result.success && result.jobId) {
        onRetry(result.jobId);
      }
    } catch (e) {
      console.error('Failed to retry:', e);
    } finally {
      setIsRetrying(false);
    }
  };

  const levelIcon = (lvl: LogLevel) => {
    if (lvl === 'error') return <XCircle className="h-4 w-4 text-red-600 dark:text-red-400" aria-hidden />;
    if (lvl === 'warn') return <AlertCircle className="h-4 w-4 text-yellow-600 dark:text-yellow-400" aria-hidden />;
    return <Info className="h-4 w-4 text-indigo-600 dark:text-indigo-400" aria-hidden />;
  };

  const checklistIcon = (status: (typeof liveRows)[0]['status']) => {
    switch (status) {
      case 'success':
        return <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-600 dark:text-emerald-400" aria-hidden />;
      case 'warning':
        return <AlertTriangle className="h-4 w-4 shrink-0 text-amber-600 dark:text-amber-400" aria-hidden />;
      case 'error':
        return <XCircle className="h-4 w-4 shrink-0 text-red-600 dark:text-red-400" aria-hidden />;
      case 'importing':
        return <Loader2 className="h-4 w-4 shrink-0 animate-spin text-indigo-600 dark:text-indigo-400" aria-hidden />;
      default:
        return <Circle className="h-4 w-4 shrink-0 text-gray-300 dark:text-gray-600" aria-hidden />;
    }
  };

  const errorEvents = getErrorEvents(events);
  const logShown = logExpanded ? events : events.slice(-IMPORT_LOG_PREVIEW_COUNT);
  const logOverflow = events.length > IMPORT_LOG_PREVIEW_COUNT;

  return (
    <div className="space-y-4">
      {errorEvents.length > 0 && (
        <div
          className="rounded-xl border-2 border-red-300 dark:border-red-700 bg-red-50 dark:bg-red-950/40 p-6"
          role="alert"
          aria-label="Import failures"
        >
          <div className="flex items-center gap-2 mb-3">
            <XCircle className="h-5 w-5 text-red-600 dark:text-red-400 shrink-0" aria-hidden />
            <h3 className="text-lg font-semibold text-red-800 dark:text-red-200">
              Failures ({errorEvents.length})
            </h3>
          </div>
          <ul className="space-y-3 max-h-72 overflow-y-auto">
            {errorEvents.map((ev) => (
              <li
                key={ev.id}
                className="rounded-lg border border-red-200 dark:border-red-800 bg-white dark:bg-gray-900/60 p-3"
              >
                <div className="flex items-start gap-2">
                  <XCircle className="h-4 w-4 text-red-600 dark:text-red-400 mt-0.5 shrink-0" aria-hidden />
                  <div className="flex-1 min-w-0">
                    <div className="text-xs text-red-600 dark:text-red-400 font-medium">{ev.code}</div>
                    <div className="text-sm text-red-900 dark:text-red-100 mt-0.5">{ev.message}</div>
                    {ev.context != null && (
                      <pre className="mt-2 text-xs text-gray-700 dark:text-gray-300 bg-gray-100 dark:bg-gray-900 rounded p-2 overflow-auto max-h-32 border border-red-100 dark:border-red-900/50">
                        {formatEventContext(ev.context)}
                      </pre>
                    )}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-5 shadow-sm">
        <div className="flex items-start justify-between gap-3 mb-4">
          <h3 className="text-base font-semibold text-gray-900 dark:text-white">Import Progress</h3>
          <Badge
            variant={
              state === 'completed'
                ? 'success'
                : state === 'failed'
                  ? 'error'
                  : state === 'canceled' || state === 'rolled-back'
                    ? 'secondary'
                    : state === 'pending-approval'
                      ? 'warning'
                      : 'default'
            }
          >
            {state === 'pending-approval' ? 'PENDING APPROVAL' : state.toUpperCase().replace(/-/g, ' ')}
          </Badge>
        </div>

        <div className="flex items-center gap-4 mb-3">
          <Progress.Root className="relative h-3 flex-1 overflow-hidden rounded-full bg-gray-200 dark:bg-gray-700" value={percent}>
            <Progress.Indicator
              className="h-full bg-gradient-to-r from-indigo-500 to-purple-600 transition-transform duration-300 ease-out"
              style={{ transform: `translateX(-${100 - (percent || 0)}%)` }}
            />
          </Progress.Root>
          <span className="text-2xl font-semibold tabular-nums text-gray-900 dark:text-white shrink-0">{percent}%</span>
        </div>

        <p className="text-sm text-gray-700 dark:text-gray-300">{primaryLine}</p>
        {etaLine && <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">{etaLine}</p>}
        {progress && progress.total > 0 && (
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
            Step {progress.completed} of {progress.total}
          </p>
        )}

        <div className="mt-4 flex flex-wrap gap-2">
          {state === 'pending-approval' ? (
            <>
              <Button
                onClick={onAccept}
                disabled={isCommitting || isRollingBack}
                className="bg-green-600 hover:bg-green-700 text-white"
              >
                <CheckCircle2 className="h-4 w-4 mr-1" />
                {isCommitting ? 'Committing...' : 'Accept & Commit'}
              </Button>
              <Button
                variant="outline"
                onClick={onReject}
                disabled={isCommitting || isRollingBack}
                className="text-red-600 border-red-300 hover:bg-red-50 dark:text-red-400 dark:border-red-700 dark:hover:bg-red-900/20"
              >
                <XCircle className="h-4 w-4 mr-1" />
                {isRollingBack ? 'Rolling Back...' : 'Reject & Rollback'}
              </Button>
            </>
          ) : state === 'failed' || state === 'canceled' ? (
            <>
              {onRetry && (
                <Button
                  onClick={onRetryClick}
                  disabled={isRetrying}
                  className="bg-indigo-600 hover:bg-indigo-700 text-white"
                >
                  <RotateCw className={`h-4 w-4 mr-1 ${isRetrying ? 'animate-spin' : ''}`} />
                  {isRetrying ? 'Starting retry...' : 'Retry Import'}
                </Button>
              )}
              <Button variant="outline" onClick={onCancel} disabled={isRetrying}>
                Cancel import
              </Button>
            </>
          ) : (state === 'queued' || state === 'running' || state === 'committing') ? (
            <Button variant="outline" onClick={onCancel}>
              <MinusCircle className="h-4 w-4 mr-1" />
              Cancel Import
            </Button>
          ) : null}
        </div>

        {state === 'completed' && summary?.['dryRun'] === true && (
          <div className="mt-4 p-3 rounded-lg bg-sky-50 dark:bg-sky-900/20 border border-sky-200 dark:border-sky-800">
            <div className="flex items-center gap-2 text-sky-800 dark:text-sky-200">
              <Info className="h-4 w-4" />
              <span className="text-sm font-medium">Dry run complete. No changes were saved.</span>
            </div>
            <p className="text-xs text-sky-700 dark:text-sky-300 mt-1 ml-6">
              Review the summary below. Uncheck &quot;Dry run (preview only)&quot; and run again to import for real.
            </p>
          </div>
        )}

        {state === 'completed' && summary?.['incrementalMode'] === true && summary?.['dryRun'] !== true && (
          <div className="mt-4 p-3 rounded-lg bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-200 dark:border-emerald-800">
            <div className="flex items-center gap-2 text-emerald-800 dark:text-emerald-200">
              <CheckCircle2 className="h-4 w-4" />
              <span className="text-sm font-medium">Incremental import complete.</span>
            </div>
            <p className="text-xs text-emerald-700 dark:text-emerald-300 mt-1 ml-6">
              Successful classes were saved; failed classes were skipped. You can open the project in Canvas or close this dialog.
            </p>
          </div>
        )}

        {transactionPending && state === 'pending-approval' && (
          <div className="mt-4 p-3 rounded-lg bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800">
            <div className="flex items-center gap-2 text-amber-800 dark:text-amber-200">
              <AlertCircle className="h-4 w-4" />
              <span className="text-sm font-medium">Transaction pending — changes will only be saved if you accept.</span>
            </div>
            <p className="text-xs text-amber-700 dark:text-amber-300 mt-1 ml-6">
              Closing this dialog or rejecting will rollback all changes.
            </p>
          </div>
        )}
      </div>

      <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-5 shadow-sm">
        <h3 className="text-base font-semibold text-gray-900 dark:text-white mb-3">Live Progress</h3>
        {liveRows.length > 0 ? (
          <ul className="max-h-80 overflow-y-auto space-y-2 pr-1" aria-label="Per-schema import status">
            {liveRows.map((row) => (
              <li key={row.id} className="flex items-start gap-2 text-sm">
                {checklistIcon(row.status)}
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                    <span className="font-medium text-gray-900 dark:text-gray-100">{row.label}</span>
                    <span className="text-gray-600 dark:text-gray-400">
                      {row.status === 'success' && 'Imported successfully'}
                      {row.status === 'warning' && 'Imported with warnings'}
                      {row.status === 'error' && 'Failed'}
                      {row.status === 'importing' && 'Importing…'}
                      {row.status === 'pending' && 'Pending'}
                    </span>
                  </div>
                  {row.detail && (
                    <p className="mt-1 text-xs text-amber-800 dark:text-amber-200 border-l-2 border-amber-300 dark:border-amber-700 pl-2">
                      {row.detail}
                    </p>
                  )}
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <div className="max-h-80 overflow-y-auto space-y-2">
            {events.length === 0 ? (
              <p className="text-sm text-gray-500 dark:text-gray-400">Waiting for import events…</p>
            ) : (
              events
                .slice()
                .reverse()
                .slice(0, 20)
                .map((ev) => (
                  <div key={ev.id} className={getLiveProgressRowClasses(ev)}>
                    {isSkippedEvent(ev) ? (
                      <MinusCircle className="h-4 w-4 text-gray-500 dark:text-gray-400 shrink-0" aria-label="Intentionally skipped" />
                    ) : (
                      levelIcon(ev.level)
                    )}
                    <div className="flex-1 min-w-0">
                      <div
                        className={`text-xs ${isSkippedEvent(ev) ? 'text-gray-400 dark:text-gray-500' : 'text-gray-500 dark:text-gray-400'}`}
                      >
                        {new Date(ev.ts).toLocaleTimeString()} • {ev.code}
                      </div>
                      <div
                        className={`text-sm ${ev.level === 'error' ? 'text-red-900 dark:text-red-100 font-medium' : isSkippedEvent(ev) ? 'text-gray-500 dark:text-gray-400' : 'text-gray-900 dark:text-gray-100'}`}
                      >
                        {ev.message}
                      </div>
                    </div>
                  </div>
                ))
            )}
          </div>
        )}
      </div>

      <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-5 shadow-sm">
        <h3 className="text-base font-semibold text-gray-900 dark:text-white mb-3">Import Log</h3>
        <div className="max-h-72 overflow-y-auto space-y-1 font-mono text-xs">
          {logShown.map((ev) => (
            <div key={ev.id} className={getImportLogLineClasses(ev)}>
              <span
                className={`mr-2 font-semibold ${isSkippedEvent(ev) ? 'text-gray-500 dark:text-gray-400' : ev.level === 'error' ? 'text-red-600 dark:text-red-400' : ev.level === 'warn' ? 'text-yellow-600 dark:text-yellow-400' : 'text-indigo-600 dark:text-indigo-400'}`}
              >
                {isSkippedEvent(ev) ? '[SKIPPED]' : `[${ev.level.toUpperCase()}]`}
              </span>
              <span className="text-gray-500 dark:text-gray-500 mr-2">{new Date(ev.ts).toLocaleTimeString()}</span>
              <span
                className={
                  isSkippedEvent(ev)
                    ? 'text-gray-500 dark:text-gray-400'
                    : ev.level === 'error'
                      ? 'text-red-900 dark:text-red-100'
                      : 'text-gray-800 dark:text-gray-200'
                }
              >
                {ev.message}
              </span>
              {ev.level === 'error' && ev.context != null && (
                <pre className="mt-1.5 text-xs text-gray-600 dark:text-gray-300 bg-gray-100 dark:bg-gray-900 rounded p-2 overflow-auto max-h-20 border border-red-200 dark:border-red-800">
                  {formatEventContext(ev.context)}
                </pre>
              )}
            </div>
          ))}
        </div>
        {logOverflow && (
          <button
            type="button"
            onClick={() => setLogExpanded((e) => !e)}
            className="mt-2 text-sm font-medium text-indigo-600 hover:text-indigo-500 dark:text-indigo-400 dark:hover:text-indigo-300"
          >
            {logExpanded ? 'Show less' : 'Show more…'}
          </button>
        )}
      </div>

      {summary && (
        <details className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-5 shadow-sm group">
          <summary className="cursor-pointer text-base font-semibold text-gray-900 dark:text-white list-none flex items-center gap-2">
            <CheckCircle2 className="h-5 w-5 text-green-600 dark:text-green-400 shrink-0" />
            Import Summary
            <span className="text-sm font-normal text-gray-500 dark:text-gray-400">(technical details)</span>
          </summary>
          <pre className="mt-3 text-xs text-gray-700 dark:text-gray-300 bg-gray-50 dark:bg-gray-900 rounded p-3 overflow-auto max-h-64">
            {JSON.stringify(summary, null, 2)}
          </pre>
        </details>
      )}
    </div>
  );
}
