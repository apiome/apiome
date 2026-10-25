/**
 * Deleting a user releases the email address and sign-in identities (V319), and a deleted account
 * never counts as an existing one: signing up again with the address works.
 */

const mockQuery = jest.fn();
const mockClientQuery = jest.fn();
const mockRelease = jest.fn();
jest.mock('../lib/db/db', () => ({
  query: (...args: unknown[]) => mockQuery(...args),
  connect: async () => ({ query: mockClientQuery, release: mockRelease }),
}));
jest.mock('../lib/db/credential-account', () => ({ upsertCredentialAccountPassword: jest.fn() }));

import { createUser, deleteUser } from '../lib/db/admin-helper';

const sqlOf = (mock: jest.Mock) => mock.mock.calls.map(([sql]) => String(sql).replace(/\s+/g, ' ').trim());

beforeEach(() => {
  mockQuery.mockReset();
  mockClientQuery.mockReset();
  mockRelease.mockReset();
});

describe('createUser', () => {
  it('only treats a live account as already holding the address', async () => {
    mockQuery
      .mockResolvedValueOnce({ rowCount: 0, rows: [] })
      .mockResolvedValueOnce({ rowCount: 1, rows: [{ id: 'u-new', email: 'ada@example.com' }] });
    const result = JSON.parse(await createUser('Ada', 'ada@example.com', '$2b$10$' + 'x'.repeat(53), false));
    expect(result.success).toBe(true);
    expect(sqlOf(mockQuery)[0]).toBe(
      'SELECT id FROM apiome.users WHERE lower(email) = lower($1) AND deleted_at IS NULL'
    );
  });
});

describe('deleteUser', () => {
  it('marks the account deleted and releases its address and identities in one transaction', async () => {
    mockClientQuery.mockImplementation(async (sql: string) =>
      sql.includes('UPDATE apiome.users') ? { rowCount: 1, rows: [{ id: 'u-1' }] } : { rowCount: 0, rows: [] }
    );
    expect(JSON.parse(await deleteUser('u-1')).success).toBe(true);

    const statements = sqlOf(mockClientQuery);
    expect(statements[0]).toBe('BEGIN');
    expect(statements[1]).toMatch(/SET deleted_at = CURRENT_TIMESTAMP, enabled = false, deleted_email = email, email = 'deleted\+' \|\| id::text \|\| '@deleted\.invalid'/);
    expect(statements[1]).toMatch(/WHERE id = \$1 AND deleted_at IS NULL/);
    expect(statements.slice(2)).toEqual([
      'DELETE FROM apiome.session WHERE "userId" = $1',
      'DELETE FROM apiome.account WHERE "userId" = $1',
      'DELETE FROM apiome.external_auth_providers WHERE user_id = $1',
      'DELETE FROM apiome.email_verification_token WHERE user_id = $1',
      'COMMIT',
    ]);
    expect(mockRelease).toHaveBeenCalledTimes(1);
  });

  it('changes nothing for an unknown or already deleted user', async () => {
    mockClientQuery.mockResolvedValue({ rowCount: 0, rows: [] });
    const result = JSON.parse(await deleteUser('u-gone'));
    expect(result).toEqual(expect.objectContaining({ success: false, error: 'User not found or already deleted' }));
    expect(sqlOf(mockClientQuery)).toEqual(['BEGIN', expect.stringMatching(/^UPDATE apiome\.users/), 'ROLLBACK']);
    expect(mockRelease).toHaveBeenCalledTimes(1);
  });

  it('rolls back when a release step fails', async () => {
    const error = jest.spyOn(console, 'error').mockImplementation(() => undefined);
    mockClientQuery.mockImplementation(async (sql: string) => {
      if (sql.includes('UPDATE apiome.users')) return { rowCount: 1, rows: [{ id: 'u-1' }] };
      if (sql.includes('external_auth_providers')) throw new Error('boom');
      return { rowCount: 0, rows: [] };
    });
    expect(JSON.parse(await deleteUser('u-1')).success).toBe(false);
    expect(sqlOf(mockClientQuery)).toContain('ROLLBACK');
    expect(sqlOf(mockClientQuery)).not.toContain('COMMIT');
    expect(mockRelease).toHaveBeenCalledTimes(1);
    error.mockRestore();
  });
});
