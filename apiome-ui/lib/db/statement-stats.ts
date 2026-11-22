/**
 * SQL statement counter for the UI's database pool (DBP-1.1, #7184).
 *
 * `lib/db/db.ts` passes every pooled client through {@link instrumentClient}, so each `query` call
 * — promise or callback form, including the ones `pool.query` makes — is timed and counted:
 *
 * - into the {@link StatementStats} of the current scope, opened with {@link runWithStatementStats}
 *   (the guarded server actions in `lib/db/helper-actions.ts` open one per call);
 * - into every open {@link captureStatements} block, whatever scope runs the statement — what
 *   {@link assertMaxQueries} uses in jest tests;
 * - into process-wide totals ({@link statementTotals}).
 *
 * The scope is taken when a statement starts, so a callback that `pg` runs later from the socket
 * still counts toward the server action that issued it.
 */

import { AsyncLocalStorage } from 'node:async_hooks';

/** Characters of each statement's SQL a capture keeps for its failure message. */
const SQL_PREVIEW_CHARS = 160;

/** Statements counted in one scope or capture. */
export type StatementStats = {
  /** Statements run. */
  count: number;
  /** Their summed wall-clock time, in milliseconds. */
  totalMs: number;
  /** A one-line preview of each statement's SQL, in order (captures only). */
  statements: string[];
  /** Whether previews are kept. */
  keepSql: boolean;
};

/** A minimal `pg` client: anything with a `query` method. */
type QueryClient = { query: (...args: any[]) => any }; // eslint-disable-line @typescript-eslint/no-explicit-any

/** Marks a client whose `query` is already wrapped. */
const INSTRUMENTED = Symbol.for('apiome.statementStats.instrumented');

const scope = new AsyncLocalStorage<StatementStats>();
const captures = new Set<StatementStats>();
const totals: StatementStats = newStats(false);

/** A fresh counter. */
function newStats(keepSql: boolean): StatementStats {
  return { count: 0, totalMs: 0, statements: [], keepSql };
}

/** One line of a statement's SQL, shortened for a failure message. */
function preview(sql: unknown): string {
  const text = String(sql ?? '')
    .split(/\s+/)
    .filter(Boolean)
    .join(' ');
  return text.length <= SQL_PREVIEW_CHARS ? text : `${text.slice(0, SQL_PREVIEW_CHARS - 1)}…`;
}

/** Add one statement to `stats`. */
function add(stats: StatementStats, elapsedMs: number, sql: unknown): void {
  stats.count += 1;
  stats.totalMs += elapsedMs;
  if (stats.keepSql) stats.statements.push(preview(sql));
}

/**
 * Count one statement in `target` (the scope it started in), the open captures and the totals.
 *
 * @param elapsedMs How long the statement took.
 * @param sql Its SQL text (kept by captures only).
 * @param target The scope's counter, taken when the statement started; defaults to the current one.
 */
export function recordStatement(
  elapsedMs: number,
  sql?: unknown,
  target: StatementStats | undefined = scope.getStore(),
): void {
  if (target) add(target, elapsedMs, sql);
  for (const capture of captures) add(capture, elapsedMs, sql);
  add(totals, elapsedMs, undefined);
}

/** The SQL text of a `query` call's first argument (a string or a `{ text }` config). */
function sqlOf(first: unknown): unknown {
  if (typeof first === 'string') return first;
  if (first && typeof first === 'object' && 'text' in first)
    return (first as { text: unknown }).text;
  return first;
}

/**
 * Wrap `client.query` so every call is counted. Idempotent: a client is wrapped once.
 *
 * @param client A `pg` client (or anything with a `query` method).
 * @returns The same client.
 */
export function instrumentClient<T extends QueryClient>(client: T): T {
  const marked = client as T & { [INSTRUMENTED]?: boolean };
  if (!client || typeof client.query !== 'function' || marked[INSTRUMENTED]) return client;
  const original = client.query;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const counted = function (this: unknown, ...args: any[]) {
    const target = scope.getStore();
    const sql = sqlOf(args[0]);
    const start = performance.now();
    const done = () => recordStatement(performance.now() - start, sql, target);
    const last = args[args.length - 1];
    if (typeof last === 'function') {
      // Callback form (what pool.query uses): count when pg answers.
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      args[args.length - 1] = (...cbArgs: any[]) => {
        done();
        return last(...cbArgs);
      };
      return original.apply(this, args);
    }
    const result = original.apply(this, args);
    if (result && typeof result.then === 'function') {
      return result.then(
        (value: unknown) => {
          done();
          return value;
        },
        (error: unknown) => {
          done();
          throw error;
        },
      );
    }
    // A submittable (cursor, stream): count it once, without a duration.
    recordStatement(0, sql, target);
    return result;
  };
  client.query = counted as T['query'];
  marked[INSTRUMENTED] = true;
  return client;
}

/**
 * Run `fn` in a new statement scope.
 *
 * @param fn The work to count (a server action's body).
 * @returns Its result and the statements it ran.
 */
export async function runWithStatementStats<T>(
  fn: () => Promise<T>,
): Promise<{ result: T; stats: StatementStats }> {
  const stats = newStats(false);
  const result = await scope.run(stats, fn);
  return { result, stats };
}

/** The current scope's counter, or `undefined` outside one. */
export function currentStatementStats(): StatementStats | undefined {
  return scope.getStore();
}

/** Process-wide totals since start (a copy). */
export function statementTotals(): { count: number; totalMs: number } {
  return { count: totals.count, totalMs: totals.totalMs };
}

/**
 * Collect every statement the process runs while `fn` runs, in any scope.
 *
 * @param fn The work to observe.
 * @returns Its result and the statements (with SQL previews).
 */
export async function captureStatements<T>(
  fn: () => Promise<T>,
): Promise<{ result: T; stats: StatementStats }> {
  const stats = newStats(true);
  captures.add(stats);
  try {
    const result = await fn();
    return { result, stats };
  } finally {
    captures.delete(stats);
  }
}

/** Thrown by {@link assertMaxQueries} when a block runs more statements than its budget. */
export class QueryBudgetExceededError extends Error {
  constructor(
    message: string,
    readonly stats: StatementStats,
  ) {
    super(message);
    this.name = 'QueryBudgetExceededError';
  }
}

/**
 * Fail when `fn` runs more than `budget` SQL statements — the jest twin of the REST
 * `assert_max_queries` helper.
 *
 * @example
 *   await assertMaxQueries(3, 'getClassesForVersion action', () => getClassesForVersion(versionId));
 *
 * @param budget The most statements `fn` may run (≥ 0).
 * @param label What `fn` is, for the failure message.
 * @param fn The work to count.
 * @returns `fn`'s result.
 * @throws RangeError For a negative budget.
 * @throws QueryBudgetExceededError Over budget; the message lists the statements.
 */
export async function assertMaxQueries<T>(
  budget: number,
  label: string,
  fn: () => Promise<T>,
): Promise<T> {
  if (!(budget >= 0)) throw new RangeError('a statement budget cannot be negative');
  const { result, stats } = await captureStatements(fn);
  if (stats.count > budget) {
    const listing = stats.statements
      .map((sql, i) => `  ${String(i + 1).padStart(3)}. ${sql}`)
      .join('\n');
    throw new QueryBudgetExceededError(
      `${label} ran ${stats.count} SQL statements; its budget is ${budget}.\n${listing}`,
      stats,
    );
  }
  return result;
}

/**
 * The statement count above which {@link warnIfOverThreshold} logs (`DB_STATEMENT_WARN_THRESHOLD`;
 * unset or `0` = never).
 */
export function statementWarnThreshold(): number {
  const parsed = parseInt(process.env.DB_STATEMENT_WARN_THRESHOLD || '', 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 0;
}

/**
 * Log a warning when a scope ran more statements than `DB_STATEMENT_WARN_THRESHOLD`.
 *
 * @param stats The scope's counter.
 * @param what What ran (for the log line).
 * @returns Whether it logged.
 */
export function warnIfOverThreshold(stats: StatementStats, what: string): boolean {
  const threshold = statementWarnThreshold();
  if (threshold === 0 || stats.count <= threshold) return false;
  console.warn(
    `[apiome-ui/db] ${what} ran ${stats.count} SQL statements in ${stats.totalMs.toFixed(1)} ms ` +
      `(DB_STATEMENT_WARN_THRESHOLD=${threshold})`,
  );
  return true;
}
