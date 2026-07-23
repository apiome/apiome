/**
 * OLO-2.4 — last-sign-in-method unlink guard.
 *
 * `unlinkExternalAccount` must never remove a user's only remaining way to sign in: their last
 * linked identity when they have no usable password. These tests drive the guard through a mocked
 * connection pool, asserting the transaction shape (lock → check → conditional delete) and the
 * stable `last-sign-in-method` rejection code. `getUserHasPassword` (which the panel uses to
 * pre-disable the final unlink) is covered too.
 */
import { describe, test, expect, jest, beforeEach } from '@jest/globals';
import { AUTH_ERROR_CODES } from '../lib/auth/account-resolution';

// Mock the connection pool: `query` for pool-level reads (getUserHasPassword) and `connect` for
// the transactional unlink. bcrypt/crypto are mocked only to keep the helper module graph light.
jest.mock('../lib/db/db', () => ({ query: jest.fn(), connect: jest.fn() }));
jest.mock('bcrypt', () => ({ compare: jest.fn(), hash: jest.fn() }));
jest.mock('crypto', () => ({ randomBytes: jest.fn(() => Buffer.from('x')) }));
jest.mock('../lib/db/plan-entitlements', () => ({
  getPlanBlockMessageForNewProject: jest.fn(async () => null),
  getPlanBlockMessageForNewVersion: jest.fn(async () => null),
}));

// These actions bind to the server session (OLO-7.3): they only act when the requested `userId`
// matches the authenticated caller. The mock defaults to a session for USER; tests that exercise
// the cross-user/anonymous refusal override it per-call.
const getAuthSessionMock = jest.fn(async () => ({ user: { user_id: 'user-1' } }) as any);
jest.mock('../lib/auth/server-session', () => ({ getAuthSession: () => getAuthSessionMock() }));

const USER = 'user-1';
const ACCOUNT = 'acct-1';

interface UnlinkWorld {
  /** Stored `users.password` value ('' = no usable password; null = user row missing). */
  password: string | null;
  /** Whether the identity row belongs to the user. */
  owned: boolean;
  /** How many identities the user has (drives the "last method" count). */
  identityCount: number;
}

/**
 * Build a mock transactional client that answers the guard's queries from a world description,
 * and records every SQL statement it saw so tests can assert what ran (and what did not).
 */
function makeClient(world: UnlinkWorld) {
  const statements: string[] = [];
  const query = jest.fn(async (sql: string) => {
    statements.push(sql);
    if (/FROM apiome\.users/.test(sql)) {
      return world.password === null
        ? { rowCount: 0, rows: [] }
        : { rowCount: 1, rows: [{ password: world.password }] };
    }
    if (/SELECT id FROM apiome\.external_auth_providers/.test(sql)) {
      return world.owned ? { rowCount: 1, rows: [{ id: ACCOUNT }] } : { rowCount: 0, rows: [] };
    }
    if (/COUNT\(\*\)/.test(sql)) {
      return { rowCount: 1, rows: [{ count: world.identityCount }] };
    }
    if (/^\s*DELETE FROM apiome\.external_auth_providers/.test(sql)) {
      return { rowCount: 1, rows: [{ provider: 'azure' }] };
    }
    // BEGIN / COMMIT / ROLLBACK
    return { rowCount: 0, rows: [] };
  });
  const release = jest.fn();
  return { client: { query, release }, statements };
}

async function callUnlink(world: UnlinkWorld) {
  const db = require('../lib/db/db');
  const { client, statements } = makeClient(world);
  (db.connect as jest.Mock).mockResolvedValue(client);
  const { unlinkExternalAccount } = await import('../lib/db/helper');
  const raw = await unlinkExternalAccount(USER, ACCOUNT);
  return { response: JSON.parse(raw), statements, client };
}

describe('unlinkExternalAccount — last-sign-in-method guard', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  test('refuses to unlink the last identity when the user has no usable password', async () => {
    const { response, statements } = await callUnlink({ password: '', owned: true, identityCount: 1 });

    expect(response.success).toBe(false);
    expect(response.code).toBe(AUTH_ERROR_CODES.LAST_SIGN_IN_METHOD);
    expect(response.error).toMatch(/only sign-in method/i);
    // The guard must not delete, and must roll the transaction back.
    expect(statements.some((s) => /DELETE FROM apiome\.external_auth_providers/.test(s))).toBe(false);
    expect(statements).toContain('ROLLBACK');
  });

  test('allows unlinking the last identity when the user has a usable password', async () => {
    const { response, statements } = await callUnlink({
      password: '$2b$10$abcdefghijklmnopqrstuv',
      owned: true,
      identityCount: 1,
    });

    expect(response.success).toBe(true);
    expect(response.provider).toBe('azure');
    expect(statements.some((s) => /DELETE FROM apiome\.external_auth_providers/.test(s))).toBe(true);
    expect(statements).toContain('COMMIT');
  });

  test('allows unlinking when another linked identity remains, even without a password', async () => {
    const { response, statements } = await callUnlink({ password: '', owned: true, identityCount: 2 });

    expect(response.success).toBe(true);
    expect(statements).toContain('COMMIT');
  });

  test('locks the user row FOR UPDATE so concurrent unlinks cannot both pass the count check', async () => {
    const { statements } = await callUnlink({ password: '', owned: true, identityCount: 2 });
    expect(statements.some((s) => /FROM apiome\.users .*FOR UPDATE/is.test(s))).toBe(true);
  });

  test('rejects an identity that does not belong to the user without deleting', async () => {
    const { response, statements } = await callUnlink({ password: '', owned: false, identityCount: 1 });

    expect(response.success).toBe(false);
    expect(response.code).toBeUndefined();
    expect(response.error).toMatch(/not found or does not belong/i);
    expect(statements.some((s) => /DELETE FROM apiome\.external_auth_providers/.test(s))).toBe(false);
    expect(statements).toContain('ROLLBACK');
  });

  test('releases the client back to the pool on both success and refusal', async () => {
    const ok = await callUnlink({ password: 'hash', owned: true, identityCount: 1 });
    expect(ok.client.release).toHaveBeenCalledTimes(1);

    const refused = await callUnlink({ password: '', owned: true, identityCount: 1 });
    expect(refused.client.release).toHaveBeenCalledTimes(1);
  });
});

describe('getUserHasPassword', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  test.each([
    ['a real hash', '$2b$10$hash', true],
    ['an empty password', '', false],
  ])('reports %s as hasPassword=%s', async (_label, storedFlag, expected) => {
    const db = require('../lib/db/db');
    // The query computes the boolean in SQL; emulate that projection here.
    (db.query as jest.Mock).mockResolvedValue({
      rowCount: 1,
      rows: [{ has_password: storedFlag !== '' }],
    });
    const { getUserHasPassword } = await import('../lib/db/helper');
    const parsed = JSON.parse(await getUserHasPassword(USER));
    expect(parsed.hasPassword).toBe(expected);
  });

  test('fails safe (hasPassword=false) when the user row is missing', async () => {
    const db = require('../lib/db/db');
    (db.query as jest.Mock).mockResolvedValue({ rowCount: 0, rows: [] });
    const { getUserHasPassword } = await import('../lib/db/helper');
    const parsed = JSON.parse(await getUserHasPassword(USER));
    expect(parsed.hasPassword).toBe(false);
  });
});

/**
 * OLO-7.3 threat-model fix: the linked-account server actions receive `userId` as a client-supplied
 * argument, so each must bind to the authenticated session and refuse when the caller is not that
 * user. A cross-user or anonymous call must touch no database and disclose nothing beyond a generic
 * not-found / fail-safe response.
 */
describe('linked-account actions — session binding (OLO-7.3 IDOR guard)', () => {
  const ATTACKER_SESSION = { user: { user_id: 'attacker' } } as any;

  beforeEach(() => {
    jest.clearAllMocks();
  });

  test('unlinkExternalAccount refuses when the session user differs from the requested userId', async () => {
    getAuthSessionMock.mockResolvedValueOnce(ATTACKER_SESSION);
    const db = require('../lib/db/db');
    const { unlinkExternalAccount } = await import('../lib/db/helper');
    const res = JSON.parse(await unlinkExternalAccount(USER, ACCOUNT));
    expect(res.success).toBe(false);
    expect(res.error).toMatch(/not found or does not belong/i);
    // No transaction is opened for a victim's account.
    expect(db.connect).not.toHaveBeenCalled();
  });

  test('unlinkExternalAccount refuses when unauthenticated', async () => {
    getAuthSessionMock.mockResolvedValueOnce(null as any);
    const db = require('../lib/db/db');
    const { unlinkExternalAccount } = await import('../lib/db/helper');
    const res = JSON.parse(await unlinkExternalAccount(USER, ACCOUNT));
    expect(res.success).toBe(false);
    expect(db.connect).not.toHaveBeenCalled();
  });

  test('getLinkedAccountsForUser discloses nothing for another user', async () => {
    getAuthSessionMock.mockResolvedValueOnce(ATTACKER_SESSION);
    const db = require('../lib/db/db');
    const { getLinkedAccountsForUser } = await import('../lib/db/helper');
    const res = JSON.parse(await getLinkedAccountsForUser(USER));
    expect(res).toEqual([]);
    expect(db.query).not.toHaveBeenCalled();
  });

  test('getUserHasPassword fails safe for another user', async () => {
    getAuthSessionMock.mockResolvedValueOnce(ATTACKER_SESSION);
    const db = require('../lib/db/db');
    const { getUserHasPassword } = await import('../lib/db/helper');
    const res = JSON.parse(await getUserHasPassword(USER));
    expect(res.hasPassword).toBe(false);
    expect(db.query).not.toHaveBeenCalled();
  });

  test('updatePersonalAccessToken refuses to overwrite another user\'s token', async () => {
    getAuthSessionMock.mockResolvedValueOnce(ATTACKER_SESSION);
    const db = require('../lib/db/db');
    const { updatePersonalAccessToken } = await import('../lib/db/helper');
    const res = JSON.parse(await updatePersonalAccessToken(USER, ACCOUNT, 'ghp_attacker'));
    expect(res.success).toBe(false);
    expect(db.query).not.toHaveBeenCalled();
  });

  test('removePersonalAccessToken refuses to wipe another user\'s token', async () => {
    getAuthSessionMock.mockResolvedValueOnce(ATTACKER_SESSION);
    const db = require('../lib/db/db');
    const { removePersonalAccessToken } = await import('../lib/db/helper');
    const res = JSON.parse(await removePersonalAccessToken(USER, ACCOUNT));
    expect(res.success).toBe(false);
    expect(db.query).not.toHaveBeenCalled();
  });

  test('addPersonalAccessToken refuses to write to another user\'s account', async () => {
    getAuthSessionMock.mockResolvedValueOnce(ATTACKER_SESSION);
    const db = require('../lib/db/db');
    const { addPersonalAccessToken } = await import('../lib/db/helper');
    const res = JSON.parse(await addPersonalAccessToken(USER, ACCOUNT, 'ghp_attacker'));
    expect(res.success).toBe(false);
    expect(db.query).not.toHaveBeenCalled();
  });
});
