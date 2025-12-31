'use client';

import { useEffect, useState } from 'react';
import * as Progress from '@radix-ui/react-progress';
import { Button } from '../../../components/ui/Button';
import { Badge } from '../../../components/ui/Badge';
import { AlertCircle, CheckCircle2, Info, XCircle, Pause } from 'lucide-react';
import { cancelImport, getImportStatus, commitImport, rollbackImport } from '../../../../../lib/db/import-actions';

interface ImportExecutionPanelProps {
  jobId: string;
  onComplete?: (succeeded: boolean) => void;
  isReviewing?: boolean; // True when viewing from 'done' step via Back button
}

type LogLevel = 'info' | 'warn' | 'error';

interface ImportEvent {
  id: string;
  ts: number;
  level: LogLevel;
  code: string;
  message: string;
  context?: any;
}

interface ProgressInfo {
  phase: 'initializing' | 'creating-project' | 'creating-version' | 'creating-properties' | 'creating-classes' | 'linking-properties' | 'verifying' | 'finalizing';
  total: number;
  completed: number;
  currentItem?: string;
}

type JobState = 'queued' | 'running' | 'pending-approval' | 'committing' | 'completed' | 'failed' | 'canceled' | 'rolled-back';

export default function ImportExecutionPanel({ jobId, onComplete, isReviewing }: ImportExecutionPanelProps) {
  const [state, setState] = useState<JobState>('queued');
  const [percent, setPercent] = useState(0);
  const [progress, setProgress] = useState<ProgressInfo | undefined>(undefined);
  const [events, setEvents] = useState<ImportEvent[]>([]);
  const [summary, setSummary] = useState<any>(null);
  const [hasNotifiedComplete, setHasNotifiedComplete] = useState(false);
  const [isCommitting, setIsCommitting] = useState(false);
  const [isRollingBack, setIsRollingBack] = useState(false);
  const [transactionPending, setTransactionPending] = useState(false);

  useEffect(() => {
    let mounted = true;
    let timer: any;

    const poll = async () => {
      try {
        const status = await getImportStatus(jobId);
        if (!mounted) return;
        setState(status.state as JobState);
        setPercent(status.percent || 0);
        setProgress(status.progress as any);
        setEvents(status.events || []);
        setSummary(status.summary || null);
        setTransactionPending((status as any).transactionPending || false);

        // Stop polling when in a terminal state or pending-approval
        if (['completed', 'failed', 'canceled', 'rolled-back', 'pending-approval'].includes(status.state)) {
          clearInterval(timer);
          // Notify parent that import reached a decision point
          if (!hasNotifiedComplete && onComplete) {
            setHasNotifiedComplete(true);
            onComplete(status.state === 'completed');
          }
        }
      } catch (e) {
        // Ignore transient errors
      }
    };

    // If reviewing (came back from done step), just poll once to get final state
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
  }, [jobId, onComplete, isReviewing, hasNotifiedComplete]);

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
        // Poll to get updated state
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

  const levelIcon = (lvl: LogLevel) => {
    if (lvl === 'error') return <XCircle className="h-4 w-4 text-red-600 dark:text-red-400"/>;
    if (lvl === 'warn') return <AlertCircle className="h-4 w-4 text-yellow-600 dark:text-yellow-400"/>;
    return <Info className="h-4 w-4 text-indigo-600 dark:text-indigo-400"/>;
  };

  return (
    <div className="space-y-6">
      {/* Overall Progress */}
      <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Import Progress</h3>
            <div className="text-sm text-gray-600 dark:text-gray-400">
              {progress?.phase?.replace(/-/g,' ') || 'starting'}{progress?.currentItem ? `: ${progress.currentItem}` : ''}
            </div>
          </div>
          <div>
            <Badge variant={
              state === 'completed' ? 'success' :
              state === 'failed' ? 'error' :
              state === 'canceled' || state === 'rolled-back' ? 'secondary' :
              state === 'pending-approval' ? 'warning' :
              'default'
            }>
              {state === 'pending-approval' ? 'PENDING APPROVAL' : state.toUpperCase().replace('-', ' ')}
            </Badge>
          </div>
        </div>
        <Progress.Root className="relative h-3 w-full overflow-hidden rounded-full bg-gray-200 dark:bg-gray-700" value={percent}>
          <Progress.Indicator
            className="h-full bg-gradient-to-r from-indigo-500 to-purple-600 transition-transform duration-300"
            style={{ transform: `translateX(-${100 - (percent || 0)}%)` }}
          />
        </Progress.Root>
        <div className="flex items-center justify-between text-xs text-gray-500 dark:text-gray-400 mt-2">
          <span>{percent}%</span>
          {progress && <span>{progress.completed} of {progress.total}</span>}
        </div>
        <div className="mt-4 flex gap-2">
          {state === 'pending-approval' ? (
            <>
              <Button
                onClick={onAccept}
                disabled={isCommitting || isRollingBack}
                className="bg-green-600 hover:bg-green-700 text-white"
              >
                <CheckCircle2 className="h-4 w-4 mr-1"/>
                {isCommitting ? 'Committing...' : 'Accept & Commit'}
              </Button>
              <Button
                variant="outline"
                onClick={onReject}
                disabled={isCommitting || isRollingBack}
                className="text-red-600 border-red-300 hover:bg-red-50 dark:text-red-400 dark:border-red-700 dark:hover:bg-red-900/20"
              >
                <XCircle className="h-4 w-4 mr-1"/>
                {isRollingBack ? 'Rolling Back...' : 'Reject & Rollback'}
              </Button>
            </>
          ) : (
            <Button variant="outline" onClick={onCancel} disabled={['completed','failed','canceled','rolled-back','pending-approval'].includes(state)}>
              <Pause className="h-4 w-4 mr-1"/> Cancel Import
            </Button>
          )}
        </div>

        {/* Transaction pending notice */}
        {transactionPending && state === 'pending-approval' && (
          <div className="mt-4 p-3 rounded-lg bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800">
            <div className="flex items-center gap-2 text-amber-800 dark:text-amber-200">
              <AlertCircle className="h-4 w-4" />
              <span className="text-sm font-medium">
                Transaction pending - changes will only be saved if you accept.
              </span>
            </div>
            <p className="text-xs text-amber-700 dark:text-amber-300 mt-1 ml-6">
              Closing this dialog or rejecting will rollback all changes.
            </p>
          </div>
        )}
      </div>

      {/* Live Progress - per event log */}
      <div className="grid grid-cols-2 gap-6">
        <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6">
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">Live Progress</h3>
          <div className="max-h-[320px] overflow-y-auto space-y-2">
            {events.slice().reverse().map(ev => (
              <div key={ev.id} className="flex items-start gap-2 p-2 rounded border border-gray-100 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/40">
                {levelIcon(ev.level)}
                <div className="flex-1 min-w-0">
                  <div className="text-xs text-gray-500 dark:text-gray-400">{new Date(ev.ts).toLocaleTimeString()} • {ev.code}</div>
                  <div className="text-sm text-gray-900 dark:text-gray-100">{ev.message}</div>
                  {ev.context && (
                    <pre className="mt-1 text-xs text-gray-600 dark:text-gray-300 bg-gray-100 dark:bg-gray-900 rounded p-2 overflow-auto max-h-24">
                      {JSON.stringify(ev.context, null, 2)}
                    </pre>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Import Log */}
        <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6">
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">Import Log</h3>
          <div className="max-h-[320px] overflow-y-auto space-y-1">
            {events.map(ev => (
              <div key={ev.id} className="text-xs font-mono">
                <span className="mr-2 px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-900 text-gray-700 dark:text-gray-300">{new Date(ev.ts).toLocaleTimeString()}</span>
                <span className={`mr-2 font-semibold ${ev.level==='error' ? 'text-red-600 dark:text-red-400' : ev.level==='warn' ? 'text-yellow-600 dark:text-yellow-400' : 'text-indigo-600 dark:text-indigo-400'}`}>[{ev.level.toUpperCase()}]</span>
                <span className="text-gray-800 dark:text-gray-200">{ev.message}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Summary */}
      {summary && (
        <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6">
          <div className="flex items-center gap-2 mb-2">
            <CheckCircle2 className="h-5 w-5 text-green-600 dark:text-green-400"/>
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Import Summary</h3>
          </div>
          <pre className="text-xs text-gray-700 dark:text-gray-300 bg-gray-50 dark:bg-gray-900 rounded p-3 overflow-auto">{JSON.stringify(summary, null, 2)}</pre>
        </div>
      )}
    </div>
  );
}
