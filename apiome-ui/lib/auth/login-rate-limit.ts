/**
 * In-memory login brute-force protection (RC1-0.3, #3610).
 *
 * A sliding-window limiter keyed by an opaque identifier (a login email for the
 * credentials provider, or a client IP for the super-admin password form). After
 * {@link LOGIN_MAX_ATTEMPTS} failed attempts inside {@link LOGIN_WINDOW_MS}, the key
 * is locked out for {@link LOGIN_BLOCK_MS}; a successful login clears the record.
 *
 * Scope / limitations: counters live in this Node process only. They reset on
 * restart and are not shared across instances or replicas. This is sufficient for
 * the single-node RC1 spine; a durable (DB/Redis) store is the documented upgrade
 * path for horizontally-scaled deployments. See docs/security/AUTH_MODEL.md.
 */

/** Failed attempts allowed inside the window before the key is locked out. */
export const LOGIN_MAX_ATTEMPTS = 5;

/** Sliding window, in milliseconds, over which failures are counted (15 minutes). */
export const LOGIN_WINDOW_MS = 15 * 60 * 1000;

/** Lockout duration, in milliseconds, once the threshold is reached (15 minutes). */
export const LOGIN_BLOCK_MS = 15 * 60 * 1000;

interface AttemptRecord {
  /** Epoch-millis timestamps of recent failures still inside the window. */
  failures: number[];
  /** Epoch-millis until which the key is locked out (0 when not locked). */
  blockedUntil: number;
}

const attempts = new Map<string, AttemptRecord>();

/** Result of a rate-limit check or failure record. */
export interface LoginRateLimitStatus {
  /** True when the key is currently locked out and the login must be refused. */
  blocked: boolean;
  /** Failed attempts remaining before lockout (0 once blocked). */
  remainingAttempts: number;
  /** Milliseconds until the lockout clears (0 when not blocked). */
  retryAfterMs: number;
}

/** Drop failure timestamps that have aged out of the sliding window. */
function prune(record: AttemptRecord, now: number): void {
  record.failures = record.failures.filter((t) => now - t < LOGIN_WINDOW_MS);
}

/**
 * Inspect the current rate-limit state for a key without recording an attempt.
 *
 * @param key Opaque identifier (e.g. `cred:user@example.com` or `admin:203.0.113.4`).
 * @param now Current epoch millis; injectable for deterministic tests.
 * @returns The lockout status for the key.
 */
export function checkLoginRateLimit(key: string, now: number = Date.now()): LoginRateLimitStatus {
  const record = attempts.get(key);
  if (!record) {
    return { blocked: false, remainingAttempts: LOGIN_MAX_ATTEMPTS, retryAfterMs: 0 };
  }

  if (record.blockedUntil > now) {
    return { blocked: true, remainingAttempts: 0, retryAfterMs: record.blockedUntil - now };
  }

  // Lockout (if any) has elapsed — clear stale failures before reporting.
  if (record.blockedUntil !== 0) {
    record.blockedUntil = 0;
    record.failures = [];
    attempts.delete(key);
    return { blocked: false, remainingAttempts: LOGIN_MAX_ATTEMPTS, retryAfterMs: 0 };
  }

  prune(record, now);
  if (record.failures.length === 0) {
    attempts.delete(key);
    return { blocked: false, remainingAttempts: LOGIN_MAX_ATTEMPTS, retryAfterMs: 0 };
  }

  return {
    blocked: false,
    remainingAttempts: Math.max(0, LOGIN_MAX_ATTEMPTS - record.failures.length),
    retryAfterMs: 0,
  };
}

/**
 * Record a failed login attempt for a key, locking it out when the threshold is hit.
 *
 * @param key Opaque identifier (see {@link checkLoginRateLimit}).
 * @param now Current epoch millis; injectable for deterministic tests.
 * @returns The resulting lockout status (blocked once the threshold is reached).
 */
export function recordLoginFailure(key: string, now: number = Date.now()): LoginRateLimitStatus {
  const record = attempts.get(key) ?? { failures: [], blockedUntil: 0 };

  // If a prior lockout has elapsed, start a fresh window.
  if (record.blockedUntil !== 0 && record.blockedUntil <= now) {
    record.blockedUntil = 0;
    record.failures = [];
  }

  prune(record, now);
  record.failures.push(now);

  if (record.failures.length >= LOGIN_MAX_ATTEMPTS) {
    record.blockedUntil = now + LOGIN_BLOCK_MS;
  }

  attempts.set(key, record);

  if (record.blockedUntil > now) {
    return { blocked: true, remainingAttempts: 0, retryAfterMs: record.blockedUntil - now };
  }
  return {
    blocked: false,
    remainingAttempts: Math.max(0, LOGIN_MAX_ATTEMPTS - record.failures.length),
    retryAfterMs: 0,
  };
}

/**
 * Clear all recorded failures for a key after a successful login.
 *
 * @param key Opaque identifier (see {@link checkLoginRateLimit}).
 */
export function recordLoginSuccess(key: string): void {
  attempts.delete(key);
}

/**
 * Build a rate-limit key for a credentials (email/password) login.
 *
 * @param email The submitted email; normalized to lower-case and trimmed.
 * @returns A namespaced key, or null when no email was supplied.
 */
export function credentialsRateLimitKey(email: string | undefined | null): string | null {
  const normalized = (email ?? '').trim().toLowerCase();
  return normalized ? `cred:${normalized}` : null;
}

/**
 * Test-only helper: clear all rate-limit state.
 *
 * @internal
 */
export function _resetLoginRateLimit(): void {
  attempts.clear();
}
