'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ExportTestTool } from './exportTestDrive';
import {
  applyToolCheckEvent,
  createNdjsonDecoder,
  startedRun,
  toolCheckConfigKey,
  toolCheckId,
  toolCheckParams,
  type ToolCheckResult,
  type ToolCheckRun,
} from './exportToolChecks';

/** The configuration whose artifact the checks run on. */
export interface ToolCheckConfig {
  /** The artifact (project) id; null before a source is chosen. */
  artifact: string | null;
  /** The revision, or null for the latest. */
  version: string | null;
  /** The selected target's key; null before one is chosen. */
  target: string | null;
  /** The changed emit options (what Verify and Generate send). */
  options: Record<string, unknown> | null | undefined;
  /** The completed export job the Review step shows, when there is one. */
  jobId: string | null;
}

/** What the toolchain check hook exposes to the console and the verify report. */
export interface UseExportToolChecksResult {
  /** Each check's console for this configuration, by {@link toolCheckId}. */
  runs: Record<string, ToolCheckRun>;
  /** Run (or re-run) one declared check. Does nothing for a check without `tool` / `check`. */
  run: (tool: ExportTestTool) => void;
  /** The settled results, in the order the checks were first run — what attaches to the verify report. */
  results: ToolCheckResult[];
}

/**
 * Run a target's declared toolchain checks on demand and hold their streamed consoles — MFX-44.6.
 *
 * Each **Run** posts to `/api/export/verify/tool-checks/{tool}` and reads the NDJSON stream as it
 * arrives, so the console fills while the tool works. The runs are keyed by configuration
 * ({@link toolCheckConfigKey}): another target, option or job starts with no results, and every
 * in-flight request is aborted (which stops the tool on the server). Re-running a check aborts its
 * previous run first.
 *
 * @param config The configuration whose artifact the checks run on.
 * @returns The consoles, the run action, and the settled results.
 */
export function useExportToolChecks(config: ToolCheckConfig): UseExportToolChecksResult {
  const { artifact, version, target, options, jobId } = config;
  const key = useMemo(
    () => toolCheckConfigKey(artifact, version, target, options, jobId),
    [artifact, version, target, options, jobId],
  );
  const [state, setState] = useState<{ key: string; runs: Record<string, ToolCheckRun> }>({ key, runs: {} });
  const controllers = useRef(new Map<string, AbortController>());
  const keyRef = useRef(key);
  keyRef.current = key;

  // A new configuration: drop the old consoles and stop whatever is still running for them.
  useEffect(() => {
    const running = controllers.current;
    return () => {
      for (const controller of running.values()) controller.abort();
      running.clear();
    };
  }, [key]);

  const runs = useMemo(() => (state.key === key ? state.runs : {}), [state, key]);

  const update = useCallback((runKey: string, id: string, change: (run: ToolCheckRun) => ToolCheckRun) => {
    setState((prev) => {
      if (runKey !== keyRef.current) return prev; // a stale stream of an earlier configuration
      const base = prev.key === runKey ? prev.runs : {};
      const current = base[id] ?? startedRun();
      return { key: runKey, runs: { ...base, [id]: change(current) } };
    });
  }, []);

  const run = useCallback(
    (tool: ExportTestTool) => {
      const params = toolCheckParams(tool);
      if (!params || !artifact || !target) return;
      const id = toolCheckId(tool);
      const runKey = keyRef.current;
      controllers.current.get(id)?.abort();
      const controller = new AbortController();
      controllers.current.set(id, controller);
      update(runKey, id, () => startedRun());

      const fail = (message: string) =>
        update(runKey, id, (current) => ({ ...current, state: 'done', error: message }));

      void (async () => {
        try {
          const res = await fetch(`/api/export/verify/tool-checks/${encodeURIComponent(params.tool)}`, {
            method: 'POST',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ artifact, version, target, options: options ?? null, check: params.check, jobId }),
            signal: controller.signal,
          });
          if (!res.ok || !res.body) {
            const data = await res.json().catch(() => ({}));
            fail(typeof data?.error === 'string' && data.error ? data.error : `The check could not start (${res.status}).`);
            return;
          }
          const reader = res.body.getReader();
          const text = new TextDecoder();
          const decoder = createNdjsonDecoder();
          let settled = false;
          for (;;) {
            const { value, done } = await reader.read();
            // `stream: true` holds a multi-byte character split across two chunks until it completes.
            const events = done ? decoder.push(text.decode()).concat(decoder.flush()) : decoder.push(text.decode(value, { stream: true }));
            for (const event of events) {
              if (event.event === 'result') settled = true;
              update(runKey, id, (current) => applyToolCheckEvent(current, event));
            }
            if (done) break;
          }
          if (!settled) fail('The check stopped before reporting a result.');
        } catch (error) {
          if (controller.signal.aborted) return;
          fail(error instanceof Error ? error.message : 'The check could not run.');
        } finally {
          if (controllers.current.get(id) === controller) controllers.current.delete(id);
        }
      })();
    },
    [artifact, version, target, options, jobId, update],
  );

  const results = useMemo(
    () => Object.values(runs).flatMap((entry) => (entry.result ? [entry.result] : [])),
    [runs],
  );

  return { runs, run, results };
}
