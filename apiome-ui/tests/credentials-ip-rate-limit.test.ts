/**
 * Per-IP brute-force protection for credentials sign-in (OLO-7.1, #4223).
 *
 * `credentialsAuthorize` must count failures per client IP (looser cap than the
 * per-account lock) so one host cannot spray attempts across many accounts, and
 * refuse locked clients before any DB or bcrypt work. One-time-code guesses count
 * against the same IP lock.
 */
import { describe, test, expect, beforeEach } from '@jest/globals';

const getUserByEmail = jest.fn();
const getUserById = jest.fn();
const consumeAuthOneTimeCode = jest.fn();

// The real helper opens a pg pool at import time; replace the whole module.
jest.mock('../lib/db/helper', () => ({
  getUserByEmail: (...args: unknown[]) => getUserByEmail(...args),
  getUserById: (...args: unknown[]) => getUserById(...args),
}));
jest.mock('../lib/db/oauth-signup', () => ({
  upsertOauthSignupPending: jest.fn(),
  consumeAuthOneTimeCode: (...args: unknown[]) => consumeAuthOneTimeCode(...args),
}));

import { credentialsAuthorize } from '../lib/auth/credentials';
import {
  CREDENTIALS_IP_MAX_ATTEMPTS,
  LOGIN_MAX_ATTEMPTS,
  checkLoginRateLimit,
  _resetLoginRateLimit,
} from '../lib/auth/login-rate-limit';

const bcrypt = require('bcrypt');

const NO_USER = { rowCount: 0, rows: [] };

beforeEach(() => {
  _resetLoginRateLimit();
  getUserByEmail.mockReset().mockResolvedValue(NO_USER);
  getUserById.mockReset();
  consumeAuthOneTimeCode.mockReset();
});

describe('credentialsAuthorize per-IP lockout', () => {
  test('locks an IP after CREDENTIALS_IP_MAX_ATTEMPTS failures across different accounts', async () => {
    const ip = '203.0.113.4';
    // Each attempt uses a fresh email, so the per-account lock never engages.
    for (let i = 0; i < CREDENTIALS_IP_MAX_ATTEMPTS; i++) {
      const result = await credentialsAuthorize(
        { email: `user${i}@example.com`, password: 'wrong' },
        ip
      );
      expect(result).toBeNull();
    }
    expect(getUserByEmail).toHaveBeenCalledTimes(CREDENTIALS_IP_MAX_ATTEMPTS);

    // The next attempt from the same IP is refused before the DB lookup.
    const blocked = await credentialsAuthorize(
      { email: 'fresh@example.com', password: 'wrong' },
      ip
    );
    expect(blocked).toBeNull();
    expect(getUserByEmail).toHaveBeenCalledTimes(CREDENTIALS_IP_MAX_ATTEMPTS);
  });

  test('a different IP keeps its own untouched budget', async () => {
    for (let i = 0; i < CREDENTIALS_IP_MAX_ATTEMPTS; i++) {
      await credentialsAuthorize({ email: `user${i}@example.com`, password: 'wrong' }, '203.0.113.4');
    }
    const calls = getUserByEmail.mock.calls.length;
    await credentialsAuthorize({ email: 'other@example.com', password: 'wrong' }, '198.51.100.7');
    expect(getUserByEmail).toHaveBeenCalledTimes(calls + 1);
  });

  test('the per-IP cap is looser than the per-account cap', async () => {
    const ip = '203.0.113.9';
    // Hammer one account: the account lock engages at LOGIN_MAX_ATTEMPTS...
    for (let i = 0; i < LOGIN_MAX_ATTEMPTS; i++) {
      await credentialsAuthorize({ email: 'victim@example.com', password: 'wrong' }, ip);
    }
    expect(checkLoginRateLimit('cred:victim@example.com').blocked).toBe(true);
    // ...but the IP can still attempt other accounts (its looser budget remains).
    const calls = getUserByEmail.mock.calls.length;
    await credentialsAuthorize({ email: 'someone-else@example.com', password: 'wrong' }, ip);
    expect(getUserByEmail).toHaveBeenCalledTimes(calls + 1);
  });

  test('a successful login clears the IP failure record', async () => {
    const ip = '203.0.113.11';
    await credentialsAuthorize({ email: 'a@example.com', password: 'wrong' }, ip);
    await credentialsAuthorize({ email: 'b@example.com', password: 'wrong' }, ip);
    expect(
      checkLoginRateLimit(`cred-ip:${ip}`, Date.now(), CREDENTIALS_IP_MAX_ATTEMPTS).remainingAttempts
    ).toBe(CREDENTIALS_IP_MAX_ATTEMPTS - 2);

    getUserByEmail.mockResolvedValue({
      rowCount: 1,
      rows: [{ id: 'u1', email: 'ok@example.com', password: bcrypt.hashSync('right', 4), enabled: true, verified: true }],
    });
    const user = await credentialsAuthorize({ email: 'ok@example.com', password: 'right' }, ip);
    expect(user).toMatchObject({ id: 'u1' });
    expect(
      checkLoginRateLimit(`cred-ip:${ip}`, Date.now(), CREDENTIALS_IP_MAX_ATTEMPTS).remainingAttempts
    ).toBe(CREDENTIALS_IP_MAX_ATTEMPTS);
  });

  test('a bad one-time code counts against the IP lock', async () => {
    const ip = '203.0.113.12';
    consumeAuthOneTimeCode.mockResolvedValue(null);
    const result = await credentialsAuthorize({ oneTimeCode: 'not-a-real-code' }, ip);
    expect(result).toBeNull();
    expect(
      checkLoginRateLimit(`cred-ip:${ip}`, Date.now(), CREDENTIALS_IP_MAX_ATTEMPTS).remainingAttempts
    ).toBe(CREDENTIALS_IP_MAX_ATTEMPTS - 1);
  });

  test('without a resolvable IP the per-account lock still works alone', async () => {
    for (let i = 0; i < LOGIN_MAX_ATTEMPTS; i++) {
      await credentialsAuthorize({ email: 'noip@example.com', password: 'wrong' });
    }
    expect(checkLoginRateLimit('cred:noip@example.com').blocked).toBe(true);
    const calls = getUserByEmail.mock.calls.length;
    // Blocked account: refused before the DB lookup.
    await credentialsAuthorize({ email: 'noip@example.com', password: 'wrong' });
    expect(getUserByEmail).toHaveBeenCalledTimes(calls);
  });
});
