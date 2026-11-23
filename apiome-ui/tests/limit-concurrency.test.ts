/**
 * DBP-1.15 (#7198): Home holds at most three pooled clients, and the limiter and the counter cache
 * behind it behave.
 */

import { describe, test, expect, jest, beforeEach } from '@jest/globals';

import { createConcurrencyLimit } from '../lib/db/limit-concurrency';
import { TtlCache } from '../lib/db/ttl-cache';

/** A promise and the functions that settle it. */
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

/** Let queued microtasks run. */
const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

describe('createConcurrencyLimit', () => {
  test('runs at most `max` tasks at once, in submission order', async () => {
    const limit = createConcurrencyLimit(2);
    const gates = [0, 1, 2, 3].map(() => deferred<number>());
    const started: number[] = [];
    const results = gates.map((gate, index) =>
      limit(() => {
        started.push(index);
        return gate.promise;
      }),
    );

    await flush();
    expect(started).toEqual([0, 1]);
    gates[1].resolve(1);
    await flush();
    expect(started).toEqual([0, 1, 2]);
    gates[0].resolve(0);
    gates[2].resolve(2);
    gates[3].resolve(3);
    await expect(Promise.all(results)).resolves.toEqual([0, 1, 2, 3]);
  });

  test('a rejected task frees its slot and rejects only its own caller', async () => {
    const limit = createConcurrencyLimit(1);
    const failed = limit(() => Promise.reject(new Error('boom')));
    const next = limit(async () => 'next');
    await expect(failed).rejects.toThrow('boom');
    await expect(next).resolves.toBe('next');
  });

  test('a task that throws synchronously is a rejection, not a crash', async () => {
    const limit = createConcurrencyLimit(1);
    await expect(
      limit(() => {
        throw new Error('sync');
      }),
    ).rejects.toThrow('sync');
    await expect(limit(async () => 1)).resolves.toBe(1);
  });

  test('a limit below one still runs tasks, one at a time', async () => {
    const limit = createConcurrencyLimit(0);
    await expect(Promise.all([limit(async () => 'a'), limit(async () => 'b')])).resolves.toEqual(['a', 'b']);
  });
});

describe('TtlCache', () => {
  test('serves a value until its age has passed', () => {
    let now = 1_000;
    const cache = new TtlCache<string>(60_000, 10, () => now);
    cache.set('user-1', 'stats');
    now += 59_999;
    expect(cache.get('user-1')).toBe('stats');
    now += 1;
    expect(cache.get('user-1')).toBeUndefined();
  });

  test('drops the oldest entry when full', () => {
    const cache = new TtlCache<number>(60_000, 2, () => 0);
    cache.set('a', 1);
    cache.set('b', 2);
    cache.set('c', 3);
    expect(cache.get('a')).toBeUndefined();
    expect(cache.get('b')).toBe(2);
    expect(cache.get('c')).toBe(3);
  });

  test('delete and clear forget entries', () => {
    const cache = new TtlCache<number>(60_000, 10, () => 0);
    cache.set('a', 1);
    cache.set('b', 2);
    cache.delete('a');
    expect(cache.get('a')).toBeUndefined();
    cache.clear();
    expect(cache.get('b')).toBeUndefined();
  });
});

describe('Home holds at most three pooled clients (DBP-1.15)', () => {
  let inFlight = 0;
  let peak = 0;
  let statements = 0;

  beforeEach(() => {
    inFlight = 0;
    peak = 0;
    statements = 0;
  });

  test('ten sections, never more than three statements running at once', async () => {
    jest.resetModules();
    jest.doMock('../lib/auth/server-session', () => ({
      getAuthSession: async () => ({ user: { user_id: 'user-1', current_tenant_id: 'tenant-1' } }),
    }));
    jest.doMock('../lib/db/db', () => ({
      query: async () => {
        statements += 1;
        inFlight += 1;
        peak = Math.max(peak, inFlight);
        await flush();
        inFlight -= 1;
        return { rows: [] };
      },
    }));
    const { getDashboardHomeForSession } = await import('../lib/db/dashboard-home');
    await getDashboardHomeForSession();
    expect(statements).toBe(10);
    expect(peak).toBe(3);
  });
});
