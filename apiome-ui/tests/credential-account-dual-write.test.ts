/**
 * Credential-account dual-write helpers (OLO-10.5, #5000).
 *
 * Every password write on the active engine mirrors the bcrypt hash into the Better Auth credential
 * account row (providerId='credential', accountId=userId) so a cutover authenticates against the
 * current password; marking an account password-less removes the row. These tests pin the SQL shape
 * and the best-effort (never-throw) contract.
 */
import { describe, test, expect, beforeEach } from '@jest/globals';

const mockQuery = jest.fn();
jest.mock('../lib/db/db', () => ({ query: (...args: unknown[]) => mockQuery(...args) }));

import {
  upsertCredentialAccountPassword,
  clearCredentialAccountPassword,
  CREDENTIAL_PROVIDER_ID,
} from '../lib/db/credential-account';

beforeEach(() => {
  mockQuery.mockReset().mockResolvedValue({ rowCount: 1, rows: [] });
});

describe('upsertCredentialAccountPassword', () => {
  test('upserts the bcrypt hash into a credential account row keyed by (providerId, accountId)', async () => {
    await upsertCredentialAccountPassword('user-1', '$2b$10$abcdefghijklmnopqrstuv');

    expect(mockQuery).toHaveBeenCalledTimes(1);
    const [sql, params] = mockQuery.mock.calls[0];
    expect(sql).toContain('INSERT INTO apiome.account');
    expect(sql).toContain('ON CONFLICT ("providerId", "accountId")');
    expect(sql).toContain('DO UPDATE SET "password" = EXCLUDED."password"');
    // params: [id, userId, accountId, providerId, password]; accountId === userId, provider = credential.
    expect(params[1]).toBe('user-1');
    expect(params[2]).toBe('user-1');
    expect(params[3]).toBe(CREDENTIAL_PROVIDER_ID);
    expect(params[4]).toBe('$2b$10$abcdefghijklmnopqrstuv');
  });

  test('an empty hash clears the row instead of storing an unusable credential', async () => {
    await upsertCredentialAccountPassword('user-2', '');

    expect(mockQuery).toHaveBeenCalledTimes(1);
    const [sql, params] = mockQuery.mock.calls[0];
    expect(sql).toContain('DELETE FROM apiome.account');
    expect(params).toEqual(['user-2', CREDENTIAL_PROVIDER_ID]);
  });

  test('skips entirely when no userId is supplied', async () => {
    await upsertCredentialAccountPassword('', 'hash');
    expect(mockQuery).not.toHaveBeenCalled();
  });

  test('never throws when the underlying write fails (best-effort, users.password authoritative)', async () => {
    mockQuery.mockRejectedValueOnce(new Error('relation "apiome.account" does not exist'));
    await expect(
      upsertCredentialAccountPassword('user-3', '$2b$10$xyz')
    ).resolves.toBeUndefined();
  });
});

describe('clearCredentialAccountPassword', () => {
  test('deletes the credential account row for the user', async () => {
    await clearCredentialAccountPassword('user-9');

    expect(mockQuery).toHaveBeenCalledTimes(1);
    const [sql, params] = mockQuery.mock.calls[0];
    expect(sql).toContain('DELETE FROM apiome.account WHERE "userId" = $1 AND "providerId" = $2');
    expect(params).toEqual(['user-9', CREDENTIAL_PROVIDER_ID]);
  });

  test('never throws when the delete fails', async () => {
    mockQuery.mockRejectedValueOnce(new Error('boom'));
    await expect(clearCredentialAccountPassword('user-9')).resolves.toBeUndefined();
  });
});
