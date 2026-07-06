'use client';

import { useCallback, useRef, useState } from 'react';
import type { ExportVerifyResponse } from './exportVerify';

export interface UseExportVerifyResult {
  /** The verify result once a run settles, else null (before the first run or after a reset). */
  result: ExportVerifyResponse | null;
  /** Whether a verification is currently in flight. */
  running: boolean;
  /** Whether a verification has been run and settled for the current configuration. */
  hasRun: boolean;
  /** The error from a failed run, else null. Unlike the advisory preview, a verify failure has no coarse fallback — the gate stays closed. */
  error: string | null;
  /** Trigger a verification for the current (target, options); resolves when it settles. */
  run: () => Promise<void>;
  /** Clear the result/error (called when the config changes so a stale verdict can't gate Generate). */
  reset: () => void;
}

/**
 * Run the one-call, pre-generation Verify for one export (MFX-42.1, #4354).
 *
 * Unlike `useExportPreview` (which auto-fetches the advisory fidelity report while a step is
 * shown), verification is **explicit**: the Verify workbench's "Run verification" action calls
 * {@link UseExportVerifyResult.run}, which POSTs to `/api/export/verify` (MFX-42.5) and returns
 * all three lenses + verdict in one dry-run. It is a real emit, so it runs on demand — never on
 * every render — and the result gates Generate until it settles with a passing (or lossy-
 * acknowledged) verdict. Changing the target or options must {@link UseExportVerifyResult.reset}
 * the result, so an out-of-date verdict never authorises a generate (auto re-verify + caching is
 * MFX-42.6).
 *
 * A run in flight is tracked by a monotonic token so a superseded response (e.g. a rapid re-run)
 * is ignored — only the latest run settles the state.
 *
 * @param artifact The artifact (project / catalog-item) id to export.
 * @param version The revision to verify (UUID or label); the latest revision when null.
 * @param target The chosen target emitter key; `run` is a no-op while null.
 * @param options The changed (non-default) option overrides sent with the verification.
 */
export function useExportVerify(
  artifact: string,
  version: string | null | undefined,
  target: string | null,
  options: Record<string, unknown> | null,
): UseExportVerifyResult {
  const [result, setResult] = useState<ExportVerifyResponse | null>(null);
  const [running, setRunning] = useState(false);
  const [hasRun, setHasRun] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Monotonic token: only the newest run may settle state; superseded runs are dropped.
  const runToken = useRef(0);

  const run = useCallback(async () => {
    if (!artifact || !target) return;
    const token = ++runToken.current;
    setRunning(true);
    setError(null);
    try {
      const res = await fetch('/api/export/verify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ artifact, version: version || null, target, options: options ?? null }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data?.success === false) {
        throw new Error(
          typeof data?.error === 'string' ? data.error : 'Could not verify this export.',
        );
      }
      if (token !== runToken.current) return;
      setResult(data as ExportVerifyResponse);
      setHasRun(true);
    } catch (e) {
      if (token !== runToken.current) return;
      setError(e instanceof Error ? e.message : 'Could not verify this export.');
      setResult(null);
      setHasRun(true);
    } finally {
      if (token === runToken.current) setRunning(false);
    }
  }, [artifact, version, target, options]);

  const reset = useCallback(() => {
    // Invalidate any in-flight run so its late response cannot settle a stale verdict.
    runToken.current += 1;
    setResult(null);
    setError(null);
    setRunning(false);
    setHasRun(false);
  }, []);

  return { result, running, hasRun, error, run, reset };
}
