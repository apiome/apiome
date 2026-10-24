/**
 * Email verification token storage (SGN-1.1, #5650; V313, V318) against a mocked pool: re-issue
 * retires unused links in one transaction and binds the new link to its sign-up's password;
 * redemption locks the row, checks that password, and only then verifies the account — making that
 * password its only credential and revoking every session (the pre-hijacking fix).
 */

const mockQuery = jest.fn();
const mockClientQuery = jest.fn();
const mockRelease = jest.fn();

jest.mock('../lib/db/db', () => ({
  query: (...args: unknown[]) => mockQuery(...args),
  connect: async () => ({ query: mockClientQuery, release: mockRelease }),
}));

import bcrypt from 'bcrypt';

import {
  findPendingSignup,
  findSignupAccount,
  issueVerificationToken,
  redeemVerificationToken,
} from '../lib/db/email-verification';

const NOW = new Date('2026-10-23T12:00:00Z');

/** The person who owns the address, and someone who signed up with it first. */
const VICTIM_PASSWORD = 'Victim#Pass1';
const ATTACKER_PASSWORD = 'Attacker#Pass1';
const VICTIM_HASH = bcrypt.hashSync(VICTIM_PASSWORD, 4);
const ATTACKER_HASH = bcrypt.hashSync(ATTACKER_PASSWORD, 4);

/** The SQL texts a client ran, whitespace-collapsed. */
function statements(): string[] {
  return mockClientQuery.mock.calls.map(([sql]) => String(sql).replace(/\s+/g, ' ').trim());
}

beforeEach(() => {
  jest.clearAllMocks();
  mockClientQuery.mockResolvedValue({ rowCount: 0, rows: [] });
});

describe('findSignupAccount', () => {
  it('matches the canonical email case-insensitively among live accounts', async () => {
    mockQuery.mockResolvedValue({
      rowCount: 1,
      rows: [{ id: 'u-1', name: 'Ada', email: 'Ada@Example.com', verified: false, enabled: true }],
    });
    await expect(findSignupAccount('ada@example.com')).resolves.toEqual({
      id: 'u-1',
      name: 'Ada',
      email: 'Ada@Example.com',
      verified: false,
      enabled: true,
    });
    const [sql, params] = mockQuery.mock.calls[0];
    expect(sql).toContain('lower(email) = $1 AND deleted_at IS NULL');
    expect(params).toEqual(['ada@example.com']);
  });

  it('returns null when no account holds the address', async () => {
    mockQuery.mockResolvedValue({ rowCount: 0, rows: [] });
    await expect(findSignupAccount('nobody@example.com')).resolves.toBeNull();
  });
});

describe('issueVerificationToken', () => {
  it('retires the user’s unused links and stores the new hash with its pending sign-up, in one transaction', async () => {
    await issueVerificationToken('u-1', 'f'.repeat(64), NOW, { passwordHash: VICTIM_HASH, name: 'Ada' });
    expect(statements()).toEqual([
      'BEGIN',
      'DELETE FROM apiome.email_verification_token WHERE user_id = $1 AND used_at IS NULL',
      'INSERT INTO apiome.email_verification_token (user_id, token_hash, expires_at, pending_password_hash, pending_name) VALUES ($1, $2, $3, $4, $5)',
      'COMMIT',
    ]);
    expect(mockClientQuery.mock.calls[2][1]).toEqual(['u-1', 'f'.repeat(64), NOW, VICTIM_HASH, 'Ada']);
    expect(mockRelease).toHaveBeenCalled();
  });

  it('stores no pending sign-up when none is given', async () => {
    await issueVerificationToken('u-1', 'f'.repeat(64), NOW);
    expect(mockClientQuery.mock.calls[2][1]).toEqual(['u-1', 'f'.repeat(64), NOW, null, null]);
  });

  it('rolls back and rethrows when the insert fails', async () => {
    mockClientQuery
      .mockResolvedValueOnce({}) // BEGIN
      .mockResolvedValueOnce({}) // DELETE
      .mockRejectedValueOnce(new Error('insert failed'));
    await expect(issueVerificationToken('u-1', 'f'.repeat(64), NOW)).rejects.toThrow('insert failed');
    expect(statements()).toContain('ROLLBACK');
    expect(mockRelease).toHaveBeenCalled();
  });
});

describe('findPendingSignup', () => {
  it('reads the newest link that carries a pending password', async () => {
    mockQuery.mockResolvedValue({ rowCount: 1, rows: [{ pending_password_hash: VICTIM_HASH, pending_name: 'Ada' }] });
    await expect(findPendingSignup('u-1')).resolves.toEqual({ passwordHash: VICTIM_HASH, name: 'Ada' });
    expect(String(mockQuery.mock.calls[0][0])).toContain('ORDER BY created_at DESC');
  });

  it('returns null when no link carries one', async () => {
    mockQuery.mockResolvedValue({ rowCount: 0, rows: [] });
    await expect(findPendingSignup('u-1')).resolves.toBeNull();
  });
});

/** The locked link row, as `redeemVerificationToken` selects it. */
function linkRow(columns: Record<string, unknown> = {}) {
  return {
    id: 't-1',
    user_id: 'u-1',
    expires_at: '2026-10-24T00:00:00Z',
    used_at: null,
    pending_password_hash: VICTIM_HASH,
    pending_name: 'Ada Lovelace',
    stored_password: ATTACKER_HASH,
    ...columns,
  };
}

/** Answer the select with `row` and every write with success. */
function serveLink(row: Record<string, unknown> | null) {
  mockClientQuery.mockImplementation(async (sql: string) =>
    String(sql).includes('FOR UPDATE')
      ? row
        ? { rowCount: 1, rows: [row] }
        : { rowCount: 0, rows: [] }
      : { rowCount: 1, rows: [] }
  );
}

describe('redeemVerificationToken', () => {
  it('verifies the account and makes the link’s password its only credential, revoking every session', async () => {
    serveLink(linkRow());
    await expect(redeemVerificationToken('a'.repeat(64), VICTIM_PASSWORD, NOW)).resolves.toEqual({
      state: 'valid',
      userId: 'u-1',
    });
    const sql = statements();
    expect(sql[1]).toContain('FOR UPDATE OF t');
    expect(sql[1]).toContain('u.deleted_at IS NULL AND u.enabled');
    expect(sql).toContain('UPDATE apiome.email_verification_token SET used_at = $2 WHERE id = $1');
    const userUpdate = mockClientQuery.mock.calls.find(([q]) => String(q).includes('UPDATE apiome.users'));
    expect(String(userUpdate?.[0])).toContain('verified = TRUE');
    expect(String(userUpdate?.[0])).toContain('password = $2');
    expect(userUpdate?.[1]).toEqual(['u-1', VICTIM_HASH, 'Ada Lovelace']);
    const credential = mockClientQuery.mock.calls.find(([q]) => String(q).includes('INSERT INTO apiome.account'));
    expect(credential?.[1]).toEqual([expect.any(String), 'u-1', 'u-1', 'credential', VICTIM_HASH]);
    expect(sql).toContain('DELETE FROM apiome.email_verification_token WHERE user_id = $1 AND used_at IS NULL');
    expect(sql).toContain('DELETE FROM apiome.session WHERE "userId" = $1');
    expect(sql[sql.length - 1]).toBe('COMMIT');
  });

  it('refuses the password an earlier sign-up for the address stored (pre-hijacking), changing nothing', async () => {
    serveLink(linkRow());
    await expect(redeemVerificationToken('a'.repeat(64), ATTACKER_PASSWORD, NOW)).resolves.toEqual({
      state: 'password-mismatch',
      userId: null,
    });
    expect(statements().some((sql) => sql.startsWith('UPDATE') || sql.startsWith('INSERT') || sql.startsWith('DELETE'))).toBe(false);
    expect(statements()).toContain('ROLLBACK');
  });

  it('checks a link issued before V318 against the stored password', async () => {
    serveLink(linkRow({ pending_password_hash: null, pending_name: null, stored_password: VICTIM_HASH }));
    await expect(redeemVerificationToken('a'.repeat(64), VICTIM_PASSWORD, NOW)).resolves.toEqual({
      state: 'valid',
      userId: 'u-1',
    });
  });

  it('refuses when there is no password to check against', async () => {
    serveLink(linkRow({ pending_password_hash: null, stored_password: null }));
    await expect(redeemVerificationToken('a'.repeat(64), VICTIM_PASSWORD, NOW)).resolves.toEqual({
      state: 'password-mismatch',
      userId: null,
    });
  });

  it.each([
    ['used', { expires_at: '2026-10-24T00:00:00Z', used_at: '2026-10-23T11:00:00Z' }],
    ['expired', { expires_at: '2026-10-23T11:00:00Z', used_at: null }],
  ])('refuses a %s link and changes nothing', async (state, columns) => {
    serveLink(linkRow(columns));
    await expect(redeemVerificationToken('a'.repeat(64), VICTIM_PASSWORD, NOW)).resolves.toEqual({ state, userId: null });
    expect(statements().some((sql) => sql.startsWith('UPDATE'))).toBe(false);
    expect(statements()).toContain('ROLLBACK');
  });

  it('calls an unknown hash invalid', async () => {
    serveLink(null);
    await expect(redeemVerificationToken('a'.repeat(64), VICTIM_PASSWORD, NOW)).resolves.toEqual({
      state: 'invalid',
      userId: null,
    });
  });
});
