'use client';

/**
 * Follow one live verification run (PFX-8.9, #7306): poll it every second while it runs, keep the
 * log the drawer shows, and say when it ends.
 *
 * Polling belongs to the page, not to the drawer: closing the drawer keeps the run — and this hook —
 * going, so the page can raise a toast when the run ends. A poll that fails keeps the last state and
 * says why; a run REST no longer knows (`404`, e.g. after 30 minutes) stops the polling.
 */

import * as React from 'react';
import {
  LIVE_POLL_MS,
  mergeLog,
  runIsOver,
  type LiveInteraction,
  type LiveLogLine,
  type LiveRun,
} from '@lib/pact-verify-live';
import { pollLiveRun, rerunInteraction, stopLiveRun } from './verifyRunApi';

/** A re-run of one interaction: going, its answer, or its refusal. */
export type RerunState =
  | { kind: 'idle' }
  | { kind: 'running'; caseId: string }
  | { kind: 'done'; caseId: string; interaction: LiveInteraction }
  | { kind: 'failed'; caseId: string; error: string };

/** What {@link useLiveRun} returns. */
export interface LiveRunHandle {
  run: LiveRun | null;
  log: LiveLogLine[];
  /** Why the newest poll, stop or re-run failed, if it did. */
  problem: string | null;
  rerun: RerunState;
  stopping: boolean;
  /** Follow a run that has just started. */
  follow: (run: LiveRun) => void;
  stop: () => Promise<void>;
  rerunOne: (sha: string, caseId: string) => Promise<void>;
}

/**
 * The hook.
 *
 * @param onFinished - Called once when the followed run ends (finished or broken).
 * @param pollMs - The poll interval (tests shorten it).
 * @returns The run, its log and what the drawer can do.
 */
export function useLiveRun(
  onFinished: (run: LiveRun) => void,
  pollMs: number = LIVE_POLL_MS,
): LiveRunHandle {
  const [run, setRun] = React.useState<LiveRun | null>(null);
  const [log, setLog] = React.useState<LiveLogLine[]>([]);
  const [problem, setProblem] = React.useState<string | null>(null);
  const [rerun, setRerun] = React.useState<RerunState>({ kind: 'idle' });
  const [stopping, setStopping] = React.useState(false);
  const cursor = React.useRef(0);
  const finished = React.useRef(onFinished);
  React.useEffect(() => {
    finished.current = onFinished;
  }, [onFinished]);

  const apply = React.useCallback((next: LiveRun) => {
    setRun(next);
    setLog((shown) => {
      const merged = mergeLog(shown, next.log);
      cursor.current = merged.length ? merged[merged.length - 1].seq : cursor.current;
      return merged;
    });
  }, []);

  const follow = React.useCallback(
    (next: LiveRun) => {
      cursor.current = 0;
      setLog([]);
      setProblem(null);
      setRerun({ kind: 'idle' });
      setStopping(false);
      apply(next);
      if (runIsOver(next)) finished.current(next);
    },
    [apply],
  );

  const runId = run?.runId ?? null;
  const going = run ? !runIsOver(run) : false;

  React.useEffect(() => {
    if (!runId || !going) return undefined;
    let live = true;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const tick = async () => {
      const answer = await pollLiveRun(runId, cursor.current);
      if (!live) return;
      if ('error' in answer) {
        setProblem(`Could not read the run: ${answer.error}`);
        if (answer.status === 404) return;
      } else {
        setProblem(null);
        apply(answer);
        if (runIsOver(answer)) {
          finished.current(answer);
          return;
        }
      }
      timer = setTimeout(() => void tick(), pollMs);
    };
    timer = setTimeout(() => void tick(), pollMs);
    return () => {
      live = false;
      if (timer) clearTimeout(timer);
    };
  }, [runId, going, pollMs, apply]);

  const stop = React.useCallback(async () => {
    if (!runId) return;
    setStopping(true);
    const answer = await stopLiveRun(runId);
    if ('error' in answer) {
      setStopping(false);
      setProblem(answer.error);
    } else {
      apply(answer);
    }
  }, [runId, apply]);

  const rerunOne = React.useCallback(
    async (sha: string, caseId: string) => {
      if (!runId) return;
      setRerun({ kind: 'running', caseId });
      const answer = await rerunInteraction(runId, sha, caseId);
      setRerun(
        'error' in answer
          ? { kind: 'failed', caseId, error: answer.error }
          : { kind: 'done', caseId, interaction: answer },
      );
      // The re-run wrote a log line; the run is over, so read it once rather than poll.
      const latest = await pollLiveRun(runId, cursor.current);
      if (!('error' in latest)) apply(latest);
    },
    [runId, apply],
  );

  return { run, log, problem, rerun, stopping, follow, stop, rerunOne };
}
