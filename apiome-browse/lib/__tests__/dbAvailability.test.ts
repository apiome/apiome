/**
 * Load shedding and the database error contract (DBP-1.27, #7210).
 *
 * The acceptance criterion: with the pool exhausted, pages return 503 with `Retry-After`, never
 * 404. `src/proxy.ts` answers the 503 from `shedReason()`; this test drives that decision with a
 * stand-in pool and with the failures `dbQuery` reports. `routeBudget.test.ts` covers the other
 * half — every loader throws instead of answering "not found".
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';

const { query } = vi.hoisted(() => ({ query: vi.fn() }));

vi.mock('../db/db', () => ({ default: { query } }));

import {
  BREAKER_MS,
  isConnectionFailure,
  noteConnectionFailure,
  registerPool,
  resetAvailability,
  shedReason,
} from '../db/availability';
import {
  DatabaseUnavailableError,
  RETRY_AFTER_SECONDS,
  unavailableProblem,
  unavailableResponse,
} from '../db/errors';
import { dbQuery, softly } from '../db/query';

/** A pool gauge: `busy` clients checked out of `max`, `waiting` requests queued. */
function pool(max: number, busy: number, waiting: number) {
  return { totalCount: busy, idleCount: 0, waitingCount: waiting, options: { max } };
}

/** pg-pool's rejection when no client became free in time. */
const CHECKOUT_TIMEOUT = new Error('timeout exceeded when trying to connect');

beforeEach(() => {
  resetAvailability();
  query.mockReset();
  vi.spyOn(console, 'error').mockImplementation(() => undefined);
});

describe('shedReason', () => {
  it('lets requests through with no pool registered, an idle pool, or a busy pool without a queue', () => {
    expect(shedReason()).toBeNull();
    registerPool({ totalCount: 3, idleCount: 3, waitingCount: 0, options: { max: 10 } });
    expect(shedReason()).toBeNull();
    registerPool(pool(10, 10, 0));
    expect(shedReason()).toBeNull();
    registerPool(pool(10, 10, 9));
    expect(shedReason()).toBeNull();
  });

  it('refuses once every client is checked out and the queue is as long as the pool', () => {
    registerPool(pool(10, 10, 10));
    expect(shedReason()).toBe('saturated');
    registerPool(pool(2, 2, 5));
    expect(shedReason()).toBe('saturated');
  });

  it('does not refuse for a queue alone: idle clients will take it', () => {
    registerPool({ totalCount: 10, idleCount: 4, waitingCount: 12, options: { max: 10 } });
    expect(shedReason()).toBeNull();
  });

  it('uses the pg default of 10 when the pool states no size', () => {
    registerPool({ totalCount: 10, idleCount: 0, waitingCount: 10, options: {} });
    expect(shedReason()).toBe('saturated');
  });

  it('refuses for a few seconds after a connection failure, then recovers by itself', () => {
    noteConnectionFailure(1_000);
    expect(shedReason(1_000)).toBe('unavailable');
    expect(shedReason(1_000 + BREAKER_MS - 1)).toBe('unavailable');
    expect(shedReason(1_000 + BREAKER_MS)).toBeNull();
  });

  it('is shared through globalThis, so the proxy bundle sees what the page bundle reported', () => {
    noteConnectionFailure();
    const shared = (globalThis as Record<string, unknown>).__apiomeBrowseDbAvailability as { unavailableUntil: number };
    expect(shared.unavailableUntil).toBeGreaterThan(Date.now());
  });
});

describe('isConnectionFailure', () => {
  it('recognizes an exhausted pool, a refused or lost connection, and a server that cannot take one', () => {
    expect(isConnectionFailure(CHECKOUT_TIMEOUT)).toBe(true);
    for (const code of ['ECONNREFUSED', 'ECONNRESET', 'ETIMEDOUT', '08006', '53300', '57P01', '57P03']) {
      expect(isConnectionFailure({ code }), code).toBe(true);
    }
  });

  it('does not count a statement that failed on a working connection', () => {
    for (const code of ['57014', '42P01', '22P02', '23505']) expect(isConnectionFailure({ code }), code).toBe(false);
    expect(isConnectionFailure(new Error('syntax error'))).toBe(false);
    expect(isConnectionFailure(null)).toBe(false);
    expect(isConnectionFailure('boom')).toBe(false);
  });
});

describe('dbQuery', () => {
  it('returns the result of a statement that ran, as text or as a named statement', async () => {
    query.mockResolvedValue({ rows: [{ n: 1 }] });
    expect((await dbQuery('scope', 'SELECT 1', [])).rows).toEqual([{ n: 1 }]);
    expect(query).toHaveBeenLastCalledWith('SELECT 1', []);
    await dbQuery('scope', { name: 'q', text: 'SELECT 1', values: [] });
    expect(query).toHaveBeenLastCalledWith({ name: 'q', text: 'SELECT 1', values: [] });
  });

  it('turns an exhausted pool into DatabaseUnavailableError and starts refusing requests', async () => {
    query.mockRejectedValue(CHECKOUT_TIMEOUT);
    const failure = await dbQuery('getPublicTenantIdentity', 'SELECT 1').catch((err) => err);
    expect(failure).toBeInstanceOf(DatabaseUnavailableError);
    expect(failure.scope).toBe('getPublicTenantIdentity');
    expect(failure.cause).toBe(CHECKOUT_TIMEOUT);
    expect(shedReason()).toBe('unavailable');
  });

  it('reports a cancelled statement as an error without refusing other requests', async () => {
    query.mockRejectedValue(Object.assign(new Error('canceling statement due to statement timeout'), { code: '57014' }));
    await expect(dbQuery('scope', 'SELECT pg_sleep(60)')).rejects.toBeInstanceOf(DatabaseUnavailableError);
    expect(shedReason()).toBeNull();
  });

  it('never puts the database error text in the message a visitor could see', async () => {
    query.mockRejectedValue(new Error('password authentication failed for user "apiome"'));
    const failure = await dbQuery('scope', 'SELECT 1').catch((err) => err);
    expect(failure.message).toBe('The catalog database is temporarily unavailable.');
  });
});

describe('softly', () => {
  it('gives a decorative list its fallback when the database fails, and nothing else', async () => {
    expect(await softly([], async () => ['row'])).toEqual(['row']);
    expect(await softly([], async () => Promise.reject(new DatabaseUnavailableError('x')))).toEqual([]);
    await expect(softly([], async () => Promise.reject(new TypeError('bug')))).rejects.toBeInstanceOf(TypeError);
  });
});

describe('the 503 responses', () => {
  it('carry Retry-After and are never cached', async () => {
    for (const response of [unavailableResponse(), unavailableProblem()]) {
      expect(response.status).toBe(503);
      expect(response.headers.get('retry-after')).toBe(String(RETRY_AFTER_SECONDS));
      expect(response.headers.get('cache-control')).toBe('no-store');
    }
    expect(await unavailableProblem().json()).toEqual({
      detail: 'The catalog is temporarily unavailable. Try again shortly.',
    });
    expect(unavailableResponse().headers.get('content-type')).toContain('text/plain');
  });
});
