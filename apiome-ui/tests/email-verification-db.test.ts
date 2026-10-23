/**
 * Email verification token storage (SGN-1.1, #5650; V313) against a mocked pool: re-issue retires
 * unused links in one transaction; redemption locks the row and verifies the account only for a
 * valid link.
 */

const mockQuery = jest.fn();
const mockClientQuery = jest.fn();
const mockRelease = jest.fn();

jest.mock('../lib/db/db', () => ({
  query: (...args: unknown[]) => mockQuery(...args),
  connect: async () => ({ query: mockClientQuery, release: mockRelease }),
}));

import {
  findSignupAccount,
  issueVerificationToken,
  redeemVerificationToken,
} from '../lib/db/email-verification';

const NOW = new Date('2026-10-23T12:00:00Z');

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
  it('retires the user’s unused links and stores the new hash, in one transaction', async () => {
    await issueVerificationToken('u-1', 'f'.repeat(64), NOW);
    expect(statements()).toEqual([
      'BEGIN',
      'DELETE FROM apiome.email_verification_token WHERE user_id = $1 AND used_at IS NULL',
      'INSERT INTO apiome.email_verification_token (user_id, token_hash, expires_at) VALUES ($1, $2, $3)',
      'COMMIT',
    ]);
    expect(mockClientQuery.mock.calls[2][1]).toEqual(['u-1', 'f'.repeat(64), NOW]);
    expect(mockRelease).toHaveBeenCalled();
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

describe('redeemVerificationToken', () => {
  it('marks a valid link used and the account verified', async () => {
    mockClientQuery.mockImplementation(async (sql: string) =>
      sql.includes('FOR UPDATE')
        ? { rowCount: 1, rows: [{ id: 't-1', user_id: 'u-1', expires_at: '2026-10-24T00:00:00Z', used_at: null }] }
        : { rowCount: 1, rows: [] }
    );
    await expect(redeemVerificationToken('a'.repeat(64), NOW)).resolves.toEqual({ state: 'valid', userId: 'u-1' });
    const sql = statements();
    expect(sql[1]).toContain('FOR UPDATE OF t');
    expect(sql[1]).toContain('u.deleted_at IS NULL AND u.enabled');
    expect(sql).toContain('UPDATE apiome.email_verification_token SET used_at = $2 WHERE id = $1');
    expect(sql).toContain('UPDATE apiome.users SET verified = TRUE, updated_at = CURRENT_TIMESTAMP WHERE id = $1');
    expect(sql[sql.length - 1]).toBe('COMMIT');
  });

  it.each([
    ['used', { expires_at: '2026-10-24T00:00:00Z', used_at: '2026-10-23T11:00:00Z' }],
    ['expired', { expires_at: '2026-10-23T11:00:00Z', used_at: null }],
  ])('refuses a %s link and changes nothing', async (state, columns) => {
    mockClientQuery.mockImplementation(async (sql: string) =>
      sql.includes('FOR UPDATE') ? { rowCount: 1, rows: [{ id: 't-1', user_id: 'u-1', ...columns }] } : {}
    );
    await expect(redeemVerificationToken('a'.repeat(64), NOW)).resolves.toEqual({ state, userId: null });
    expect(statements().some((sql) => sql.startsWith('UPDATE'))).toBe(false);
    expect(statements()).toContain('ROLLBACK');
  });

  it('calls an unknown hash invalid', async () => {
    await expect(redeemVerificationToken('a'.repeat(64), NOW)).resolves.toEqual({ state: 'invalid', userId: null });
  });
});
