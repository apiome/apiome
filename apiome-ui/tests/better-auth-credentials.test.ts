/**
 * Better Auth credential wiring (OLO-10.5, #5000): bcrypt password hash/verify and the per-account +
 * per-IP rate-limit hooks around `/sign-in/email`.
 *
 * These prove the two invariants the migration must preserve when credential login moves onto Better
 * Auth: (1) the relocated bcrypt hashes verify (and new hashes stay bcrypt), and (2) the exact
 * sliding-window limiter from the NextAuth path guards the Better Auth sign-in endpoint.
 */
import { describe, test, expect, beforeEach } from '@jest/globals';

// `better-auth/api` is ESM-only; stub createAuthMiddleware to return the handler and provide a minimal
// APIError so `throw new APIError(...)` is observable.
jest.mock('better-auth/api', () => ({
  createAuthMiddleware: (handler: unknown) => handler,
  APIError: class APIError extends Error {
    status: string;
    body: { message?: string; code?: string } | undefined;
    constructor(status: string, body?: { message?: string; code?: string }) {
      super(body?.message);
      this.status = status;
      this.body = body;
    }
  },
}));

import {
  bcryptPasswordConfig,
  credentialRateLimitBefore,
  credentialRateLimitAfter,
  SIGN_IN_EMAIL_PATH,
  BCRYPT_COST,
} from '../lib/auth/better-auth-credentials';
import {
  AUTH_RATE_LIMITED_CODE,
  CREDENTIALS_IP_MAX_ATTEMPTS,
  LOGIN_MAX_ATTEMPTS,
  checkLoginRateLimit,
  credentialsRateLimitKey,
  credentialsIpRateLimitKey,
  recordLoginFailure,
  _resetLoginRateLimit,
} from '../lib/auth/login-rate-limit';

// eslint-disable-next-line @typescript-eslint/no-require-imports -- native module, ts-jest CJS transform
const bcrypt = require('bcrypt');

/** A hook is a `createAuthMiddleware` result; under the mock it is the bare handler. */
type Hook = (ctx: unknown) => Promise<void>;
const before = credentialRateLimitBefore as unknown as Hook;
const after = credentialRateLimitAfter as unknown as Hook;

/** Build a Better Auth middleware context for a credential sign-in attempt. */
const signInCtx = (email: string | undefined, ip: string, newSession?: unknown) => ({
  path: SIGN_IN_EMAIL_PATH,
  body: email === undefined ? {} : { email },
  headers: new Headers(ip ? { 'x-forwarded-for': ip } : {}),
  context: { newSession: newSession ?? null },
});

beforeEach(() => {
  _resetLoginRateLimit();
});

describe('bcryptPasswordConfig — preserves bcrypt verification of relocated hashes', () => {
  test('verify accepts a correct password against an existing bcrypt hash', async () => {
    // A hash exactly as apiome stores it (cost 10, $2b$) — the relocation copies these verbatim.
    const hash = bcrypt.hashSync('correct horse battery staple', 10);
    await expect(bcryptPasswordConfig.verify({ hash, password: 'correct horse battery staple' })).resolves.toBe(true);
  });

  test('verify rejects a wrong password', async () => {
    const hash = bcrypt.hashSync('right', 10);
    await expect(bcryptPasswordConfig.verify({ hash, password: 'wrong' })).resolves.toBe(false);
  });

  test('verify accepts legacy $2a$ hashes (older bcrypt prefix)', async () => {
    // bcrypt.compare transparently handles $2a$/$2b$; simulate an older-prefix hash.
    const hash = bcrypt.hashSync('legacy-pass', 10).replace(/^\$2b\$/, '$2a$');
    await expect(bcryptPasswordConfig.verify({ hash, password: 'legacy-pass' })).resolves.toBe(true);
  });

  test('hash produces a bcrypt hash at the codebase cost that verifies (rollback-compatible)', async () => {
    const hash = await bcryptPasswordConfig.hash('new-password');
    expect(hash).toMatch(/^\$2[ab]\$10\$/); // bcrypt, cost 10
    expect(BCRYPT_COST).toBe(10);
    await expect(bcryptPasswordConfig.verify({ hash, password: 'new-password' })).resolves.toBe(true);
  });
});

describe('credentialRateLimitBefore — refuses locked attempts before password work', () => {
  test('passes through when neither account nor IP is locked', async () => {
    await expect(
      before(signInCtx('ada@example.com', '203.0.113.1'))
    ).resolves.toBeUndefined();
  });

  test('throws a structured 429 once the per-account lock engages', async () => {
    const key = credentialsRateLimitKey('ada@example.com')!;
    for (let i = 0; i < LOGIN_MAX_ATTEMPTS; i++) recordLoginFailure(key);

    await expect(
      before(signInCtx('ada@example.com', '203.0.113.2'))
    ).rejects.toMatchObject({ status: 'TOO_MANY_REQUESTS', body: { code: AUTH_RATE_LIMITED_CODE } });
  });

  test('throws once the looser per-IP lock engages, regardless of account', async () => {
    const ip = '203.0.113.3';
    const ipKey = credentialsIpRateLimitKey(ip)!;
    for (let i = 0; i < CREDENTIALS_IP_MAX_ATTEMPTS; i++) {
      recordLoginFailure(ipKey, Date.now(), CREDENTIALS_IP_MAX_ATTEMPTS);
    }
    await expect(
      before(signInCtx('fresh@example.com', ip))
    ).rejects.toMatchObject({ status: 'TOO_MANY_REQUESTS', body: { code: AUTH_RATE_LIMITED_CODE } });
  });

  test('ignores requests to any path other than /sign-in/email', async () => {
    const key = credentialsRateLimitKey('ada@example.com')!;
    for (let i = 0; i < LOGIN_MAX_ATTEMPTS; i++) recordLoginFailure(key);
    const ctx = { ...signInCtx('ada@example.com', '203.0.113.4'), path: '/get-session' };
    await expect(before(ctx)).resolves.toBeUndefined();
  });
});

describe('credentialRateLimitAfter — records the sign-in outcome on both limiters', () => {
  test('a failed sign-in (no session) records a failure against account and IP', async () => {
    const email = 'ada@example.com';
    const ip = '203.0.113.5';
    await after(signInCtx(email, ip, null));

    const acct = checkLoginRateLimit(credentialsRateLimitKey(email)!);
    expect(acct.remainingAttempts).toBe(LOGIN_MAX_ATTEMPTS - 1);
    const perIp = checkLoginRateLimit(credentialsIpRateLimitKey(ip)!, Date.now(), CREDENTIALS_IP_MAX_ATTEMPTS);
    expect(perIp.remainingAttempts).toBe(CREDENTIALS_IP_MAX_ATTEMPTS - 1);
  });

  test('repeated failures lock the account after LOGIN_MAX_ATTEMPTS, then before-hook refuses', async () => {
    const email = 'mallory@example.com';
    const ip = '203.0.113.6';
    for (let i = 0; i < LOGIN_MAX_ATTEMPTS; i++) {
      await after(signInCtx(email, ip, null));
    }
    expect(checkLoginRateLimit(credentialsRateLimitKey(email)!).blocked).toBe(true);
    await expect(
      before(signInCtx(email, ip))
    ).rejects.toMatchObject({ status: 'TOO_MANY_REQUESTS' });
  });

  test('a successful sign-in (newSession present) clears the account and IP locks', async () => {
    const email = 'ada@example.com';
    const ip = '203.0.113.7';
    // Accumulate a few failures, then succeed.
    for (let i = 0; i < 3; i++) await after(signInCtx(email, ip, null));
    await after(signInCtx(email, ip, { id: 'session-1' }));

    expect(checkLoginRateLimit(credentialsRateLimitKey(email)!).remainingAttempts).toBe(LOGIN_MAX_ATTEMPTS);
    expect(
      checkLoginRateLimit(credentialsIpRateLimitKey(ip)!, Date.now(), CREDENTIALS_IP_MAX_ATTEMPTS).remainingAttempts
    ).toBe(CREDENTIALS_IP_MAX_ATTEMPTS);
  });

  test('ignores non-sign-in paths', async () => {
    const ctx = { ...signInCtx('ada@example.com', '203.0.113.8', null), path: '/get-session' };
    await after(ctx);
    expect(checkLoginRateLimit(credentialsRateLimitKey('ada@example.com')!).remainingAttempts).toBe(
      LOGIN_MAX_ATTEMPTS
    );
  });
});
