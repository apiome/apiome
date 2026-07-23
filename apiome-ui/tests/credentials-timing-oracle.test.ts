/**
 * OLO-7.3 — credentials sign-in must not leak account existence via timing.
 *
 * `credentialsAuthorize` previously only ran bcrypt when the email resolved to an account with a
 * usable password, so a non-existent (or OAuth-only, password-less) email answered measurably
 * faster — a timing oracle an attacker could use to enumerate valid emails even within the
 * rate-limit budget. The fix always performs exactly one bcrypt comparison (against a fixed decoy
 * hash on the miss path). These tests assert that invariant by spying on `bcrypt.compareSync`.
 */
import { describe, test, expect, beforeEach } from '@jest/globals';

const getUserByEmail = jest.fn();
const getUserById = jest.fn();

// The real helper opens a pg pool at import time; replace the whole module.
jest.mock('../lib/db/helper', () => ({
  getUserByEmail: (...args: unknown[]) => getUserByEmail(...args),
  getUserById: (...args: unknown[]) => getUserById(...args),
}));
jest.mock('../lib/db/oauth-signup', () => ({
  upsertOauthSignupPending: jest.fn(),
  consumeAuthOneTimeCode: jest.fn(),
}));

import { credentialsAuthorize } from '../lib/auth/credentials';
import { _resetLoginRateLimit } from '../lib/auth/login-rate-limit';

const bcrypt = require('bcrypt');

const NO_USER = { rowCount: 0, rows: [] };
const userRow = (password: string | null) => ({
  rowCount: 1,
  rows: [{ id: 'u1', email: 'ada@example.com', password, enabled: true, verified: true }],
});

let compareSpy: jest.SpiedFunction<typeof bcrypt.compareSync>;

beforeEach(() => {
  _resetLoginRateLimit();
  getUserByEmail.mockReset().mockResolvedValue(NO_USER);
  getUserById.mockReset();
  compareSpy = jest.spyOn(bcrypt, 'compareSync');
});

afterEach(() => {
  compareSpy.mockRestore();
});

describe('credentialsAuthorize — constant-work timing (enumeration resistance)', () => {
  test('runs one bcrypt comparison even when the email has no account', async () => {
    const result = await credentialsAuthorize(
      { email: 'nobody@example.com', password: 'guess' },
      '203.0.113.20'
    );
    expect(result).toBeNull();
    // The decoy compare still runs, so a miss costs the same as a wrong password.
    expect(compareSpy).toHaveBeenCalledTimes(1);
  });

  test('runs one bcrypt comparison for an OAuth-only account with no usable password', async () => {
    getUserByEmail.mockResolvedValue(userRow(''));
    const result = await credentialsAuthorize(
      { email: 'oauth-only@example.com', password: 'guess' },
      '203.0.113.21'
    );
    expect(result).toBeNull();
    expect(compareSpy).toHaveBeenCalledTimes(1);
  });

  test('runs one bcrypt comparison when the account exists but the password is wrong', async () => {
    getUserByEmail.mockResolvedValue(userRow(bcrypt.hashSync('right', 4)));
    const result = await credentialsAuthorize(
      { email: 'ada@example.com', password: 'wrong' },
      '203.0.113.22'
    );
    expect(result).toBeNull();
    expect(compareSpy).toHaveBeenCalledTimes(1);
  });

  test('still authenticates a correct password (the decoy never blocks a real login)', async () => {
    getUserByEmail.mockResolvedValue(userRow(bcrypt.hashSync('right', 4)));
    const result = await credentialsAuthorize(
      { email: 'ada@example.com', password: 'right' },
      '203.0.113.23'
    );
    expect(result).toMatchObject({ id: 'u1' });
    // The returned user object never carries the password hash.
    expect((result as Record<string, unknown>).password).toBeUndefined();
  });

  test('the decoy hash never matches a login (null email/password guard aside)', async () => {
    // A blank password is rejected before any hashing (no oracle, no work).
    const result = await credentialsAuthorize(
      { email: 'nobody@example.com', password: '' },
      '203.0.113.24'
    );
    expect(result).toBeNull();
    expect(compareSpy).not.toHaveBeenCalled();
  });
});
