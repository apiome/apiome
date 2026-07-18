/**
 * In-memory login brute-force protection (RC1-0.3, #3610; extended by OLO-7.1, #4223).
 *
 * Two limiters share this module:
 *
 * 1. A **failure-based sliding-window** limiter keyed by an opaque identifier (a
 *    login email or a client IP). After the allowed failed attempts inside
 *    {@link LOGIN_WINDOW_MS}, the key is locked out for {@link LOGIN_BLOCK_MS}; a
 *    successful login clears the record. The credentials provider keys this per
 *    account (`cred:<email>`, {@link LOGIN_MAX_ATTEMPTS}) *and* per client IP
 *    (`cred-ip:<ip>`, the looser {@link CREDENTIALS_IP_MAX_ATTEMPTS} so shared
 *    NATs are not punished for one noisy neighbour).
 *
 * 2. A **fixed-window request budget** ({@link checkRequestBudget}) that counts
 *    every call, for auth route handlers where each request has cost regardless
 *    of outcome (link-intent, signup-intent). Over-budget callers get a
 *    structured 429 carrying {@link AUTH_RATE_LIMITED_CODE}.
 *
 * Scope / limitations: counters live in this Node process only. They reset on
 * restart and are not shared across instances or replicas. This is sufficient for
 * the single-node RC1 spine; a durable (DB/Redis) store is the documented upgrade
 * path for horizontally-scaled deployments. See docs/security/AUTH_MODEL.md.
 */

/** Failed attempts allowed inside the window before the key is locked out. */
export const LOGIN_MAX_ATTEMPTS = 5;

/**
 * Failed attempts allowed per client IP for credentials sign-in (OLO-7.1). Looser
 * than the per-account cap so one abusive neighbour on a shared NAT does not lock
 * out the whole office, while still bounding cross-account spraying from one host.
 */
export const CREDENTIALS_IP_MAX_ATTEMPTS = 20;

/**
 * Stable structured code for auth-surface 429 responses (OLO-7.1). Matches the
 * REST side (`apiome-rest/src/app/auth_rate_limit.py`) so callers handle the
 * throttle identically on both surfaces.
 */
export const AUTH_RATE_LIMITED_CODE = 'auth-rate-limited';

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
 * @param maxAttempts Failure threshold for this key (defaults to {@link LOGIN_MAX_ATTEMPTS};
 *   per-IP credentials keys pass {@link CREDENTIALS_IP_MAX_ATTEMPTS}).
 * @returns The lockout status for the key.
 */
export function checkLoginRateLimit(
  key: string,
  now: number = Date.now(),
  maxAttempts: number = LOGIN_MAX_ATTEMPTS
): LoginRateLimitStatus {
  const record = attempts.get(key);
  if (!record) {
    return { blocked: false, remainingAttempts: maxAttempts, retryAfterMs: 0 };
  }

  if (record.blockedUntil > now) {
    return { blocked: true, remainingAttempts: 0, retryAfterMs: record.blockedUntil - now };
  }

  // Lockout (if any) has elapsed — clear stale failures before reporting.
  if (record.blockedUntil !== 0) {
    record.blockedUntil = 0;
    record.failures = [];
    attempts.delete(key);
    return { blocked: false, remainingAttempts: maxAttempts, retryAfterMs: 0 };
  }

  prune(record, now);
  if (record.failures.length === 0) {
    attempts.delete(key);
    return { blocked: false, remainingAttempts: maxAttempts, retryAfterMs: 0 };
  }

  return {
    blocked: false,
    remainingAttempts: Math.max(0, maxAttempts - record.failures.length),
    retryAfterMs: 0,
  };
}

/**
 * Record a failed login attempt for a key, locking it out when the threshold is hit.
 *
 * @param key Opaque identifier (see {@link checkLoginRateLimit}).
 * @param now Current epoch millis; injectable for deterministic tests.
 * @param maxAttempts Failure threshold for this key (defaults to {@link LOGIN_MAX_ATTEMPTS}).
 * @returns The resulting lockout status (blocked once the threshold is reached).
 */
export function recordLoginFailure(
  key: string,
  now: number = Date.now(),
  maxAttempts: number = LOGIN_MAX_ATTEMPTS
): LoginRateLimitStatus {
  const record = attempts.get(key) ?? { failures: [], blockedUntil: 0 };

  // If a prior lockout has elapsed, start a fresh window.
  if (record.blockedUntil !== 0 && record.blockedUntil <= now) {
    record.blockedUntil = 0;
    record.failures = [];
  }

  prune(record, now);
  record.failures.push(now);

  if (record.failures.length >= maxAttempts) {
    record.blockedUntil = now + LOGIN_BLOCK_MS;
  }

  attempts.set(key, record);

  if (record.blockedUntil > now) {
    return { blocked: true, remainingAttempts: 0, retryAfterMs: record.blockedUntil - now };
  }
  return {
    blocked: false,
    remainingAttempts: Math.max(0, maxAttempts - record.failures.length),
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
 * Build the per-IP rate-limit key for a credentials login (OLO-7.1).
 *
 * @param clientIp The resolved client IP (see `lib/auth/client-ip.ts`); `'unknown'`
 *   is a valid key — callers without forwarded headers share one coarse bucket.
 * @returns A namespaced key, or null when no IP string was supplied at all.
 */
export function credentialsIpRateLimitKey(clientIp: string | undefined | null): string | null {
  const normalized = (clientIp ?? '').trim();
  return normalized ? `cred-ip:${normalized}` : null;
}

// ---------------------------------------------------------------------------
// Fixed-window request budget (OLO-7.1) — counts every request, not failures.
// ---------------------------------------------------------------------------

/** Requests allowed per key per {@link AUTH_ROUTE_WINDOW_MS} on auth route handlers. */
export const AUTH_ROUTE_MAX_REQUESTS = 10;

/** Fixed-window length for the auth route request budget (1 minute). */
export const AUTH_ROUTE_WINDOW_MS = 60 * 1000;

interface BudgetWindow {
  /** Requests recorded in the current window. */
  count: number;
  /** Epoch millis at which the window rolls over. */
  resetAt: number;
}

const budgets = new Map<string, BudgetWindow>();

/** Result of a request-budget check. */
export interface RequestBudgetStatus {
  /** True when this request is within the budget and may proceed. */
  allowed: boolean;
  /** Requests left in the current window (0 when over budget). */
  remaining: number;
  /** Milliseconds until the window rolls over (0 when allowed). */
  retryAfterMs: number;
}

/**
 * Record a request against a fixed-window budget and report whether it may proceed.
 *
 * Unlike the failure-based limiter above, every call counts — use this for auth
 * route handlers whose requests have cost regardless of outcome (link-intent,
 * signup-intent cookies).
 *
 * @param key Namespaced bucket key (e.g. `link:ip:203.0.113.4`).
 * @param limit Max requests per window (defaults to {@link AUTH_ROUTE_MAX_REQUESTS}).
 * @param windowMs Window length in millis (defaults to {@link AUTH_ROUTE_WINDOW_MS}).
 * @param now Current epoch millis; injectable for deterministic tests.
 * @returns Whether the request is allowed, plus remaining budget and retry delay.
 */
export function checkRequestBudget(
  key: string,
  limit: number = AUTH_ROUTE_MAX_REQUESTS,
  windowMs: number = AUTH_ROUTE_WINDOW_MS,
  now: number = Date.now()
): RequestBudgetStatus {
  const effectiveLimit = Math.max(1, limit);
  let window = budgets.get(key);
  if (!window || now >= window.resetAt) {
    window = { count: 0, resetAt: now + windowMs };
    budgets.set(key, window);
  }
  window.count += 1;

  const allowed = window.count <= effectiveLimit;
  return {
    allowed,
    remaining: Math.max(0, effectiveLimit - window.count),
    retryAfterMs: allowed ? 0 : Math.max(0, window.resetAt - now),
  };
}

/**
 * Test-only helper: clear all rate-limit state (failure records and request budgets).
 *
 * @internal
 */
export function _resetLoginRateLimit(): void {
  attempts.clear();
  budgets.clear();
}
