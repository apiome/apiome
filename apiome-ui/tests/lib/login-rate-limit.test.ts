/**
 * Tests for the in-memory login brute-force limiter (RC1-0.3, #3610) and the
 * auth-surface extensions (OLO-7.1, #4223): per-key failure thresholds, the
 * per-IP credentials key, and the fixed-window request budget.
 */
import {
  LOGIN_MAX_ATTEMPTS,
  LOGIN_BLOCK_MS,
  LOGIN_WINDOW_MS,
  CREDENTIALS_IP_MAX_ATTEMPTS,
  AUTH_ROUTE_MAX_REQUESTS,
  AUTH_ROUTE_WINDOW_MS,
  AUTH_RATE_LIMITED_CODE,
  checkLoginRateLimit,
  recordLoginFailure,
  recordLoginSuccess,
  credentialsRateLimitKey,
  credentialsIpRateLimitKey,
  checkRequestBudget,
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

describe('credentialsIpRateLimitKey (OLO-7.1)', () => {
  it('builds a namespaced key from the resolved IP', () => {
    expect(credentialsIpRateLimitKey('203.0.113.4')).toBe('cred-ip:203.0.113.4');
  });

  it("keeps 'unknown' as a valid coarse bucket", () => {
    expect(credentialsIpRateLimitKey('unknown')).toBe('cred-ip:unknown');
  });

  it('returns null when no IP string is supplied', () => {
    expect(credentialsIpRateLimitKey('')).toBeNull();
    expect(credentialsIpRateLimitKey('   ')).toBeNull();
    expect(credentialsIpRateLimitKey(undefined)).toBeNull();
    expect(credentialsIpRateLimitKey(null)).toBeNull();
  });
});

describe('per-key failure thresholds (OLO-7.1)', () => {
  const IP_KEY = 'cred-ip:203.0.113.4';

  it('honours a custom maxAttempts before locking out', () => {
    const now = 6_000_000;
    let status = checkLoginRateLimit(IP_KEY, now, CREDENTIALS_IP_MAX_ATTEMPTS);
    expect(status.remainingAttempts).toBe(CREDENTIALS_IP_MAX_ATTEMPTS);

    for (let i = 0; i < CREDENTIALS_IP_MAX_ATTEMPTS - 1; i++) {
      status = recordLoginFailure(IP_KEY, now + i, CREDENTIALS_IP_MAX_ATTEMPTS);
      expect(status.blocked).toBe(false);
    }
    // The default (lower) threshold would have locked this key long ago.
    expect(CREDENTIALS_IP_MAX_ATTEMPTS).toBeGreaterThan(LOGIN_MAX_ATTEMPTS);

    status = recordLoginFailure(IP_KEY, now + CREDENTIALS_IP_MAX_ATTEMPTS, CREDENTIALS_IP_MAX_ATTEMPTS);
    expect(status.blocked).toBe(true);
    expect(checkLoginRateLimit(IP_KEY, now + CREDENTIALS_IP_MAX_ATTEMPTS + 1, CREDENTIALS_IP_MAX_ATTEMPTS).blocked).toBe(true);
  });

  it('keeps the default threshold when maxAttempts is omitted', () => {
    const now = 7_000_000;
    let status = { blocked: false, remainingAttempts: 0, retryAfterMs: 0 };
    for (let i = 0; i < LOGIN_MAX_ATTEMPTS; i++) {
      status = recordLoginFailure(IP_KEY, now + i);
    }
    expect(status.blocked).toBe(true);
  });
});

describe('checkRequestBudget (OLO-7.1)', () => {
  const KEY = 'link:ip:203.0.113.4';

  it('allows requests up to the limit and then refuses with a retry delay', () => {
    const now = 8_000_000;
    for (let i = 0; i < 3; i++) {
      const status = checkRequestBudget(KEY, 3, 60_000, now + i);
      expect(status.allowed).toBe(true);
      expect(status.remaining).toBe(3 - (i + 1));
      expect(status.retryAfterMs).toBe(0);
    }
    const refused = checkRequestBudget(KEY, 3, 60_000, now + 10);
    expect(refused.allowed).toBe(false);
    expect(refused.remaining).toBe(0);
    expect(refused.retryAfterMs).toBeGreaterThan(0);
    expect(refused.retryAfterMs).toBeLessThanOrEqual(60_000);
  });

  it('rolls the window over and admits requests again', () => {
    const now = 9_000_000;
    expect(checkRequestBudget(KEY, 1, 60_000, now).allowed).toBe(true);
    expect(checkRequestBudget(KEY, 1, 60_000, now + 100).allowed).toBe(false);
    expect(checkRequestBudget(KEY, 1, 60_000, now + 60_000).allowed).toBe(true);
  });

  it('isolates distinct keys', () => {
    const now = 10_000_000;
    expect(checkRequestBudget('link:ip:a', 1, 60_000, now).allowed).toBe(true);
    expect(checkRequestBudget('link:ip:b', 1, 60_000, now).allowed).toBe(true);
    expect(checkRequestBudget('link:ip:a', 1, 60_000, now + 1).allowed).toBe(false);
  });

  it('clamps a misconfigured limit of zero to one instead of refusing everything forever', () => {
    const now = 11_000_000;
    expect(checkRequestBudget(KEY, 0, 60_000, now).allowed).toBe(true);
    expect(checkRequestBudget(KEY, 0, 60_000, now + 1).allowed).toBe(false);
  });

  it('uses the documented defaults', () => {
    const now = 12_000_000;
    for (let i = 0; i < AUTH_ROUTE_MAX_REQUESTS; i++) {
      expect(checkRequestBudget(KEY, undefined, undefined, now + i).allowed).toBe(true);
    }
    const refused = checkRequestBudget(KEY, undefined, undefined, now + AUTH_ROUTE_MAX_REQUESTS);
    expect(refused.allowed).toBe(false);
    expect(refused.retryAfterMs).toBeLessThanOrEqual(AUTH_ROUTE_WINDOW_MS);
  });

  it('is cleared by the test-only reset helper', () => {
    const now = 13_000_000;
    expect(checkRequestBudget(KEY, 1, 60_000, now).allowed).toBe(true);
    expect(checkRequestBudget(KEY, 1, 60_000, now + 1).allowed).toBe(false);
    _resetLoginRateLimit();
    expect(checkRequestBudget(KEY, 1, 60_000, now + 2).allowed).toBe(true);
  });
});

describe('AUTH_RATE_LIMITED_CODE', () => {
  it('matches the REST-side stable code (apiome-rest/src/app/auth_rate_limit.py)', () => {
    expect(AUTH_RATE_LIMITED_CODE).toBe('auth-rate-limited');
  });
});
