/**
 * Tests for the in-memory login brute-force limiter (RC1-0.3, #3610).
 */
import {
  LOGIN_MAX_ATTEMPTS,
  LOGIN_BLOCK_MS,
  LOGIN_WINDOW_MS,
  checkLoginRateLimit,
  recordLoginFailure,
  recordLoginSuccess,
  credentialsRateLimitKey,
  _resetLoginRateLimit,
} from '@lib/auth/login-rate-limit';

const KEY = 'cred:user@example.com';

beforeEach(() => {
  _resetLoginRateLimit();
});

describe('checkLoginRateLimit', () => {
  it('reports an unseen key as unblocked with full attempts', () => {
    const status = checkLoginRateLimit(KEY);
    expect(status.blocked).toBe(false);
    expect(status.remainingAttempts).toBe(LOGIN_MAX_ATTEMPTS);
    expect(status.retryAfterMs).toBe(0);
  });
});

describe('recordLoginFailure', () => {
  it('decrements remaining attempts up to the threshold', () => {
    const now = 1_000_000;
    for (let i = 1; i < LOGIN_MAX_ATTEMPTS; i++) {
      const status = recordLoginFailure(KEY, now + i);
      expect(status.blocked).toBe(false);
      expect(status.remainingAttempts).toBe(LOGIN_MAX_ATTEMPTS - i);
    }
    expect(checkLoginRateLimit(KEY, now + LOGIN_MAX_ATTEMPTS).blocked).toBe(false);
  });

  it('blocks once the threshold is reached and reports retry-after', () => {
    const now = 2_000_000;
    let status = { blocked: false, remainingAttempts: 0, retryAfterMs: 0 };
    for (let i = 0; i < LOGIN_MAX_ATTEMPTS; i++) {
      status = recordLoginFailure(KEY, now + i);
    }
    expect(status.blocked).toBe(true);
    expect(status.retryAfterMs).toBeGreaterThan(0);
    expect(status.retryAfterMs).toBeLessThanOrEqual(LOGIN_BLOCK_MS);
    expect(checkLoginRateLimit(KEY, now + 10).blocked).toBe(true);
  });

  it('clears the lockout once the block window elapses', () => {
    const now = 3_000_000;
    for (let i = 0; i < LOGIN_MAX_ATTEMPTS; i++) {
      recordLoginFailure(KEY, now + i);
    }
    expect(checkLoginRateLimit(KEY, now + 1).blocked).toBe(true);
    // The block is measured from the last failure timestamp (now + MAX_ATTEMPTS - 1).
    const after = now + LOGIN_MAX_ATTEMPTS + LOGIN_BLOCK_MS;
    expect(checkLoginRateLimit(KEY, after).blocked).toBe(false);
    expect(checkLoginRateLimit(KEY, after).remainingAttempts).toBe(LOGIN_MAX_ATTEMPTS);
  });

  it('ages out failures older than the sliding window', () => {
    const now = 4_000_000;
    // Two early failures, then a gap longer than the window, then more failures.
    recordLoginFailure(KEY, now);
    recordLoginFailure(KEY, now + 1);
    const later = now + LOGIN_WINDOW_MS + 10;
    // The two old failures have aged out, so these do not reach the threshold.
    for (let i = 0; i < LOGIN_MAX_ATTEMPTS - 1; i++) {
      const status = recordLoginFailure(KEY, later + i);
      expect(status.blocked).toBe(false);
    }
  });
});

describe('recordLoginSuccess', () => {
  it('resets accumulated failures', () => {
    const now = 5_000_000;
    for (let i = 0; i < LOGIN_MAX_ATTEMPTS - 1; i++) {
      recordLoginFailure(KEY, now + i);
    }
    recordLoginSuccess(KEY);
    const status = checkLoginRateLimit(KEY, now + 100);
    expect(status.blocked).toBe(false);
    expect(status.remainingAttempts).toBe(LOGIN_MAX_ATTEMPTS);
  });
});

describe('credentialsRateLimitKey', () => {
  it('normalizes email to a namespaced lower-case key', () => {
    expect(credentialsRateLimitKey('  User@Example.COM ')).toBe('cred:user@example.com');
  });

  it('returns null when no email is supplied', () => {
    expect(credentialsRateLimitKey('')).toBeNull();
    expect(credentialsRateLimitKey(undefined)).toBeNull();
    expect(credentialsRateLimitKey(null)).toBeNull();
  });
});
