/**
 * Run async work with at most N tasks in flight (DBP-1.15, #7198).
 *
 * Home loads ten independent sections. Started all at once with `Promise.all`, each `pool.query`
 * checks out its own client, so one page could hold every client of the UI pool (`max: 10`) and
 * make every other request wait. {@link createConcurrencyLimit} queues the extra tasks instead, so
 * one page never holds more pooled clients than the limit.
 *
 * Deliberately **not** a `'use server'` module.
 */

/** Runs a task when a slot is free and resolves with its result. */
export type ConcurrencyLimit = <T>(task: () => Promise<T>) => Promise<T>;

/**
 * Create a limiter.
 *
 * Tasks start in the order they were submitted. A task that rejects frees its slot like one that
 * resolves, and its rejection is passed to its own caller only.
 *
 * @param max How many tasks may run at once; values below 1 are treated as 1.
 * @returns A function that runs a task under the limit.
 */
export function createConcurrencyLimit(max: number): ConcurrencyLimit {
  const limit = Math.max(1, Math.floor(max) || 1);
  let running = 0;
  const waiting: Array<() => void> = [];

  /** Start the next queued task, if a slot is free. */
  const next = () => {
    if (running >= limit) return;
    const start = waiting.shift();
    if (start) start();
  };

  return <T>(task: () => Promise<T>) =>
    new Promise<T>((resolve, reject) => {
      waiting.push(() => {
        running += 1;
        Promise.resolve()
          .then(task)
          .then(resolve, reject)
          .finally(() => {
            running -= 1;
            next();
          });
      });
      next();
    });
}
