'use client';

/**
 * Follow one migration run (PFX-8.16, #7313): read it every moment while it runs, keep the log the
 * **Copy** step shows, and say when it ends.
 *
 * The run is the server's — leaving the page stops this hook, not the run. A read that fails keeps
 * the last state and says why; a run REST no longer knows (`404`) stops the polling.
 */

import * as React from 'react';
import { MIGRATION_POLL_MS, mergeLog, runIsOver, type MigrationLogLine, type MigrationRun } from '@lib/pact-migration';
import { describeFailure } from '../pactPacticipants/describeFailure';
import { readMigration, stopMigration } from './migrateApi';

/** What {@link useMigrationRun} returns. */
export interface MigrationRunHandle {
  run: MigrationRun | null;
  log: MigrationLogLine[];
  /** Why the newest read or stop failed, if it did. */
  problem: string | null;
  stopping: boolean;
  /** Follow a run (one just started, resumed, or opened from Past migrations); `null` lets go of it. */
  follow: (run: MigrationRun | null) => void;
  stop: () => Promise<void>;
}

/**
 * The hook.
 *
 * @param onFinished - Called once when the followed run ends.
 * @param pollMs - The poll interval (tests shorten it).
 * @returns The run, its log and what the step can do.
 */
export function useMigrationRun(
  onFinished: (run: MigrationRun) => void,
  pollMs: number = MIGRATION_POLL_MS,
): MigrationRunHandle {
  const [run, setRun] = React.useState<MigrationRun | null>(null);
  const [log, setLog] = React.useState<MigrationLogLine[]>([]);
  const [problem, setProblem] = React.useState<string | null>(null);
  const [stopping, setStopping] = React.useState(false);
  const cursor = React.useRef(0);
  const finished = React.useRef(onFinished);
  React.useEffect(() => {
    finished.current = onFinished;
  }, [onFinished]);

  const apply = React.useCallback((next: MigrationRun) => {
    setRun(next);
    setLog((shown) => {
      const merged = mergeLog(shown, next.log ?? []);
      cursor.current = merged.length ? merged[merged.length - 1].seq : cursor.current;
      return merged;
    });
  }, []);

  const follow = React.useCallback(
    (next: MigrationRun | null) => {
      cursor.current = 0;
      setLog([]);
      setProblem(null);
      setStopping(false);
      if (next === null) setRun(null);
      else apply(next);
    },
    [apply],
  );

  const runId = run?.id ?? null;
  const going = run ? !runIsOver(run) : false;

  React.useEffect(() => {
    if (!runId || !going) return undefined;
    let live = true;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const tick = async () => {
      const answer = await readMigration(runId, cursor.current);
      if (!live) return;
      if ('failure' in answer) {
        setProblem(`Could not read the migration: ${answer.failure}`);
        if (answer.status === 404) return;
      } else {
        setProblem(null);
        apply(answer);
        if (runIsOver(answer)) {
          setStopping(false);
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
    try {
      apply(await stopMigration(runId));
    } catch (caught) {
      setStopping(false);
      setProblem(describeFailure(caught, 'Could not stop the migration'));
    }
  }, [runId, apply]);

  return { run, log, problem, stopping, follow, stop };
}
