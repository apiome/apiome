/**
 * lib/db/statement-stats — the SQL statement counter on the UI pool (DBP-1.1, #7184).
 *
 * Pins the wrapper around a client's `query` (promise, callback and submittable forms, errors,
 * wrapped once), scopes that stay apart when they run concurrently, captures that see every
 * scope, `assertMaxQueries`, the warn threshold, and that `lib/db/db.ts` wraps each pooled client.
 */

import { describe, test, expect, jest, afterEach } from '@jest/globals';

import {
  QueryBudgetExceededError,
  assertMaxQueries,
  captureStatements,
  currentStatementStats,
  instrumentClient,
  runWithStatementStats,
  statementTotals,
  warnIfOverThreshold,
} from '../lib/db/statement-stats';

/** A fake client whose `query` answers after `delayMs`, in promise or callback form. */
function fakeClient(delayMs = 1) {
  return {
    calls: 0,
    query(...args: unknown[]): unknown {
      this.calls += 1;
      const text = String(args[0]);
      const last = args[args.length - 1];
      const answer = { rows: [{ text }], rowCount: 1 };
      if (typeof last === 'function') {
        setTimeout(() => (last as (e: unknown, r: unknown) => void)(null, answer), delayMs);
        return undefined;
      }
      if (text.startsWith('FAIL'))
        return new Promise((_, reject) => setTimeout(() => reject(new Error('boom')), delayMs));
      if (text.startsWith('STREAM')) return { submittable: true };
      return new Promise((resolve) => setTimeout(() => resolve(answer), delayMs));
    },
  };
}

afterEach(() => {
  delete process.env.DB_STATEMENT_WARN_THRESHOLD;
  jest.restoreAllMocks();
});

describe('instrumentClient', () => {
  test('counts promise queries and passes their result through', async () => {
    const client = instrumentClient(fakeClient());
    const { result, stats } = await captureStatements(
      () => client.query('SELECT 1') as Promise<{ rows: unknown[] }>,
    );
    expect(result.rows).toEqual([{ text: 'SELECT 1' }]);
    expect(stats.count).toBe(1);
    expect(stats.totalMs).toBeGreaterThan(0);
    expect(stats.statements).toEqual(['SELECT 1']);
  });

  test('counts callback queries (the form pool.query uses) when pg answers', async () => {
    const client = instrumentClient(fakeClient());
    const { stats } = await captureStatements(
      () =>
        new Promise<void>((resolve) => {
          client.query({ text: 'SELECT  2\n FROM t' }, [], () => resolve());
        }),
    );
    expect(stats.statements).toEqual(['SELECT 2 FROM t']);
  });

  test('counts a failed query and rethrows its error', async () => {
    const client = instrumentClient(fakeClient());
    const { stats } = await captureStatements(async () => {
      await expect(client.query('FAIL now') as Promise<unknown>).rejects.toThrow('boom');
    });
    expect(stats.count).toBe(1);
  });

  test('counts a submittable once, without a duration', async () => {
    const client = instrumentClient(fakeClient());
    const { stats } = await captureStatements(async () => client.query('STREAM rows'));
    expect(stats.count).toBe(1);
  });

  test('wraps a client once', async () => {
    const client = instrumentClient(instrumentClient(fakeClient()));
    const { stats } = await captureStatements(() => client.query('SELECT 1') as Promise<unknown>);
    expect(stats.count).toBe(1);
    expect(client.calls).toBe(1);
  });

  test('adds to the process-wide totals', async () => {
    const before = statementTotals().count;
    await instrumentClient(fakeClient()).query('SELECT 1');
    expect(statementTotals().count).toBe(before + 1);
  });
});

describe('scopes', () => {
  test('concurrent scopes count only their own statements, callbacks included', async () => {
    const client = instrumentClient(fakeClient(5));
    const one = runWithStatementStats(async () => {
      await client.query('SELECT a');
      await client.query('SELECT b');
    });
    const two = runWithStatementStats(
      () =>
        new Promise<void>((resolve) => {
          client.query('SELECT c', [], () => resolve());
        }),
    );
    const [a, b] = await Promise.all([one, two]);
    expect(a.stats.count).toBe(2);
    expect(b.stats.count).toBe(1);
    expect(a.stats.statements).toEqual([]); // scopes keep no SQL text
  });

  test('there is no scope outside runWithStatementStats', () => {
    expect(currentStatementStats()).toBeUndefined();
  });
});

describe('assertMaxQueries', () => {
  test('returns the result within budget', async () => {
    const client = instrumentClient(fakeClient());
    await expect(
      assertMaxQueries(1, 'one read', async () => (await client.query('SELECT 1'), 'ok')),
    ).resolves.toBe('ok');
  });

  test('fails over budget and lists the statements', async () => {
    const client = instrumentClient(fakeClient());
    const error = await assertMaxQueries(1, 'two reads', async () => {
      await client.query('SELECT a FROM t');
      await client.query('SELECT b FROM t');
    }).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(QueryBudgetExceededError);
    expect((error as QueryBudgetExceededError).stats.count).toBe(2);
    expect(String((error as Error).message)).toMatch(
      /two reads ran 2 SQL statements; its budget is 1\.\n\s+1\. SELECT a FROM t\n\s+2\. SELECT b FROM t/,
    );
  });

  test('rejects a negative budget', async () => {
    await expect(assertMaxQueries(-1, 'x', async () => undefined)).rejects.toThrow(RangeError);
  });

  test('shortens long SQL in the listing', async () => {
    const client = instrumentClient(fakeClient());
    const { stats } = await captureStatements(
      () => client.query(`SELECT ${'x, '.repeat(200)}`) as Promise<unknown>,
    );
    expect(stats.statements[0]).toHaveLength(160);
    expect(stats.statements[0].endsWith('…')).toBe(true);
  });
});

describe('warnIfOverThreshold', () => {
  const stats = { count: 12, totalMs: 3.5, statements: [], keepSql: false };

  test('is off by default', () => {
    const warn = jest.spyOn(console, 'warn').mockImplementation(() => undefined);
    expect(warnIfOverThreshold(stats, 'an action')).toBe(false);
    expect(warn).not.toHaveBeenCalled();
  });

  test('warns above DB_STATEMENT_WARN_THRESHOLD', () => {
    process.env.DB_STATEMENT_WARN_THRESHOLD = '10';
    const warn = jest.spyOn(console, 'warn').mockImplementation(() => undefined);
    expect(warnIfOverThreshold(stats, 'an action')).toBe(true);
    expect(String(warn.mock.calls[0][0])).toContain('an action ran 12 SQL statements in 3.5 ms');
    expect(warnIfOverThreshold({ ...stats, count: 10 }, 'an action')).toBe(false);
  });
});

describe('lib/db/db.ts', () => {
  test('wraps every client the pool connects', () => {
    jest.isolateModules(() => {
      const handlers: Record<string, (client: unknown) => void> = {};
      jest.doMock('pg', () => ({
        Pool: jest.fn(() => ({
          on: (event: string, handler: (client: unknown) => void) => {
            handlers[event] = handler;
          },
        })),
      }));
      jest.spyOn(console, 'warn').mockImplementation(() => undefined);
      // eslint-disable-next-line @typescript-eslint/no-require-imports
      require('../lib/db/db');
      const client = fakeClient();
      const original = client.query;
      handlers.connect(client);
      expect(client.query).not.toBe(original);
    });
  });
});
