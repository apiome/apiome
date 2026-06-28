'use client';

/**
 * MCP discovery live-status panel (V2-MCP-24.1 / MCAT-10.1).
 *
 * Rendered inside the Import dialog after the "MCP Server" source creates an endpoint and kicks off
 * a discovery run. It polls the job until it reaches a terminal state, surfaces the live status, and
 * reports completion (success + produced version id, or the failure) back to the dialog.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { CheckCircle2, Loader2, Network, XCircle } from 'lucide-react';
import {
  discoveryFailureMessage,
  discoveryStatusLabel,
  discoverySummary,
  isJobSuccess,
  isTerminalJobState,
  versionIdFromJob,
  type McpDiscoveryJob,
} from './mcp/mcpImportFlow';

export interface McpDiscoveryPanelProps {
  endpointId: string;
  jobId: string;
  /** Endpoint display name, for the header. */
  endpointName: string;
  /** Fired once when the job reaches a terminal state. */
  onComplete: (succeeded: boolean, versionId: string | null) => void;
  /** Poll interval in ms (injectable for tests). */
  pollIntervalMs?: number;
}

export default function McpDiscoveryPanel({
  endpointId,
  jobId,
  endpointName,
  onComplete,
  pollIntervalMs = 1500,
}: McpDiscoveryPanelProps) {
  const [job, setJob] = useState<McpDiscoveryJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const completedRef = useRef(false);
  const onCompleteRef = useRef(onComplete);
  onCompleteRef.current = onComplete;

  const finish = useCallback((finalJob: McpDiscoveryJob | null, succeeded: boolean) => {
    if (completedRef.current) return;
    completedRef.current = true;
    onCompleteRef.current(succeeded, versionIdFromJob(finalJob));
  }, []);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const poll = async () => {
      try {
        const res = await fetch(
          `/api/mcp/endpoints/${encodeURIComponent(endpointId)}/discover/${encodeURIComponent(jobId)}`,
          { credentials: 'include', cache: 'no-store' },
        );
        const data = await res.json().catch(() => ({}));
        if (cancelled) return;
        if (!res.ok) {
          throw new Error(typeof data.error === 'string' ? data.error : res.statusText);
        }
        const nextJob = (data.job ?? null) as McpDiscoveryJob | null;
        setJob(nextJob);
        if (nextJob && isTerminalJobState(nextJob.state)) {
          const succeeded = isJobSuccess(nextJob);
          if (!succeeded) {
            setError(discoveryFailureMessage(nextJob));
          }
          finish(nextJob, succeeded);
          return;
        }
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : 'Discovery failed.');
        finish(null, false);
        return;
      }
      timer = setTimeout(() => void poll(), pollIntervalMs);
    };

    void poll();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [endpointId, jobId, pollIntervalMs, finish]);

  const state = job?.state;
  const succeeded = isJobSuccess(job);
  const terminal = isTerminalJobState(state) || !!error;
  const summary = succeeded ? discoverySummary(job) : null;

  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-4 py-10 text-center">
      <div
        className={`flex h-16 w-16 items-center justify-center rounded-2xl ${
          terminal
            ? succeeded
              ? 'bg-green-500 text-white'
              : 'bg-red-500 text-white'
            : 'bg-indigo-500 text-white'
        }`}
      >
        {!terminal ? (
          <Loader2 className="h-8 w-8 animate-spin" aria-hidden />
        ) : succeeded ? (
          <CheckCircle2 className="h-8 w-8" aria-hidden />
        ) : (
          <XCircle className="h-8 w-8" aria-hidden />
        )}
      </div>

      <div>
        <h3 className="flex items-center justify-center gap-2 text-lg font-semibold text-gray-900 dark:text-white">
          <Network className="h-4 w-4 text-indigo-500" aria-hidden />
          {endpointName}
        </h3>
        <p
          className={`mt-1 text-sm ${
            terminal && !succeeded
              ? 'text-red-600 dark:text-red-400'
              : 'text-gray-600 dark:text-gray-400'
          }`}
          aria-live="polite"
        >
          {error ? error : discoveryStatusLabel(state)}
        </p>
        {summary && (
          <p className="mt-1 text-xs text-gray-500 dark:text-gray-400" aria-live="polite">
            {summary}
          </p>
        )}
      </div>

      {!terminal && (
        <p className="text-xs text-gray-500 dark:text-gray-400">
          This can take a few moments while we connect and list capabilities.
        </p>
      )}
    </div>
  );
}
