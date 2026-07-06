'use client';

import { useCallback, useState, useSyncExternalStore } from 'react';
import {
  cancelExportJob,
  clearExportJob,
  exportJobScopeKey,
  getExportJob,
  retryExportJob,
  startExportJob,
  subscribeExportJob,
  type ExportJobSubmitParams,
  type TrackedExportJob,
} from './exportJobTracker';

/** The submit fields the Generate phase supplies (the scope's artifact/version are implicit). */
export type ExportJobStartParams = Omit<ExportJobSubmitParams, 'artifact' | 'version'>;

/** What {@link useExportJob} exposes to the Generate phase. */
export interface UseExportJobResult {
  /** The tracked job for this scope, or null when none is running/finished. */
  job: TrackedExportJob | null;
  /** Whether a submit (start or retry) request is currently in flight. */
  submitting: boolean;
  /** Submit an export job for this scope, replacing any job already tracked. */
  start: (params: ExportJobStartParams) => void;
  /** Re-submit the scope's job (Retry), optionally overriding fields (e.g. `confirm: true`). */
  retry: (overrides?: Partial<ExportJobSubmitParams>) => void;
  /** Request cancellation of the scope's running job. */
  cancel: () => void;
  /** Forget the scope's tracked job (e.g. after the configuration changed). */
  clear: () => void;
}

/**
 * Subscribe to (and drive) the async export job for one Studio scope (MFX-46.2, #4380).
 *
 * A thin `useSyncExternalStore` view over the module-level {@link subscribeExportJob tracker}: the
 * tracker owns polling, persistence, background completion toasts, and resume-across-navigation,
 * while this hook just reflects the scope's current job and forwards the start/retry/cancel/clear
 * actions. Because the tracker is process-wide, a job keeps running (and this hook re-attaches to
 * it) even when the Generate phase unmounts and remounts.
 *
 * @param artifact The artifact (project / catalog-item) id being exported.
 * @param version The revision being exported (UUID or label), or null for the latest.
 * @returns The tracked job and the lifecycle actions.
 */
export function useExportJob(
  artifact: string,
  version: string | null | undefined,
): UseExportJobResult {
  const scopeKey = exportJobScopeKey(artifact, version);
  const [submitting, setSubmitting] = useState(false);

  const subscribe = useCallback(
    (onChange: () => void) => subscribeExportJob(scopeKey, onChange),
    [scopeKey],
  );
  const job = useSyncExternalStore(
    subscribe,
    () => getExportJob(scopeKey),
    () => null,
  );

  const start = useCallback(
    (params: ExportJobStartParams) => {
      setSubmitting(true);
      void startExportJob({ artifact, version: version ?? null, ...params }).finally(() =>
        setSubmitting(false),
      );
    },
    [artifact, version],
  );

  const retry = useCallback(
    (overrides?: Partial<ExportJobSubmitParams>) => {
      setSubmitting(true);
      void retryExportJob(scopeKey, overrides).finally(() => setSubmitting(false));
    },
    [scopeKey],
  );

  const cancel = useCallback(() => {
    void cancelExportJob(scopeKey);
  }, [scopeKey]);

  const clear = useCallback(() => {
    clearExportJob(scopeKey);
  }, [scopeKey]);

  return { job, submitting, start, retry, cancel, clear };
}
