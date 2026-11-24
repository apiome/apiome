/**
 * Whether the database can take another page view right now (DBP-1.27, #7210).
 *
 * `src/proxy.ts` asks {@link shedReason} before a request is rendered and answers `503` with
 * `Retry-After` when there is one. Two signals:
 *
 *   - **Saturation.** Every pooled client is checked out and at least as many requests are already
 *     waiting for one as the pool holds. A request added to that queue would wait for the whole
 *     queue in front of it and then most likely time out; refusing it at once is cheaper for the
 *     visitor and lets the queue drain.
 *   - **A recent connection failure.** A statement failed because no connection could be had (the
 *     pool's checkout timed out, the server refused or dropped the connection). For
 *     {@link BREAKER_MS} afterwards requests are refused instead of each waiting for the same
 *     failure.
 *
 * The state lives on `globalThis`, not in a module variable: Next bundles the proxy separately from
 * the pages, so the two would not share a module instance, but they run in one Node.js process and
 * share its global object. `lib/db/db.ts` registers the pool; `lib/db/query.ts` reports failures.
 *
 * This module imports nothing, so the proxy bundle stays free of `pg`.
 */

/** How long requests are refused after a connection failure, in milliseconds. */
export const BREAKER_MS = 5000;

/** The part of a `pg` pool the saturation check reads. */
export interface PoolGauge {
  /** Clients the pool holds (idle and checked out). */
  totalCount: number;
  /** Clients nobody is using. */
  idleCount: number;
  /** Requests waiting for a client. */
  waitingCount: number;
  /** The pool's size limit. */
  options: { max?: number };
}

/** What `globalThis` carries between the proxy and the pages. */
interface AvailabilityState {
  pool?: PoolGauge;
  /** Epoch milliseconds until which requests are refused after a connection failure. */
  unavailableUntil: number;
}

const STATE_KEY = '__apiomeBrowseDbAvailability';

/** The shared state, created on first use. */
function state(): AvailabilityState {
  const holder = globalThis as unknown as Record<string, AvailabilityState | undefined>;
  let current = holder[STATE_KEY];
  if (!current) {
    current = { unavailableUntil: 0 };
    holder[STATE_KEY] = current;
  }
  return current;
}

/**
 * Make a pool's gauges visible to the proxy. Called once by `lib/db/db.ts`.
 *
 * @param pool - The Browse connection pool.
 */
export function registerPool(pool: PoolGauge): void {
  state().pool = pool;
}

/** `pg-pool`'s message when no client became free within `connectionTimeoutMillis`. */
const CHECKOUT_TIMEOUT = /timeout exceeded when trying to connect/i;

/** Node error codes of a connection that could not be made or was lost. */
const CONNECTION_CODES = new Set(['ECONNREFUSED', 'ECONNRESET', 'ETIMEDOUT', 'EPIPE', 'ENOTFOUND', 'EHOSTUNREACH']);

/**
 * Whether an error from the pool means "no connection", as opposed to a statement that failed on a
 * working connection.
 *
 * PostgreSQL's class 08 (connection exception), 53 (insufficient resources, including
 * `too_many_connections`) and 57P (operator intervention: shutdown, crash recovery) count; a
 * cancelled statement (`57014`) does not — one slow statement is not an outage.
 *
 * @param err - Anything `pool.query` rejected with.
 * @returns True for a connection-level failure.
 */
export function isConnectionFailure(err: unknown): boolean {
  if (typeof err !== 'object' || err === null) return false;
  const { code, message } = err as { code?: unknown; message?: unknown };
  if (typeof message === 'string' && CHECKOUT_TIMEOUT.test(message)) return true;
  if (typeof code !== 'string') return false;
  return CONNECTION_CODES.has(code) || code.startsWith('08') || code.startsWith('53') || code.startsWith('57P');
}

/**
 * Record a connection failure: requests are refused for {@link BREAKER_MS} from now.
 *
 * @param now - The clock, in epoch milliseconds; injectable for tests.
 */
export function noteConnectionFailure(now: number = Date.now()): void {
  state().unavailableUntil = now + BREAKER_MS;
}

/**
 * Why a new request should be refused, if it should.
 *
 * @param now - The clock, in epoch milliseconds; injectable for tests.
 * @returns `'saturated'`, `'unavailable'`, or `null` when the request may be rendered.
 */
export function shedReason(now: number = Date.now()): 'saturated' | 'unavailable' | null {
  const current = state();
  if (now < current.unavailableUntil) return 'unavailable';
  const pool = current.pool;
  if (!pool) return null;
  const max = pool.options.max ?? 10;
  const busy = pool.totalCount - pool.idleCount;
  return busy >= max && pool.waitingCount >= max ? 'saturated' : null;
}

/** Forget everything. For tests. */
export function resetAvailability(): void {
  const current = state();
  current.pool = undefined;
  current.unavailableUntil = 0;
}
