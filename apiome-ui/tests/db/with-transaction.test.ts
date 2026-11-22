/**
 * `withTransaction` runs every statement of a transaction on one checked-out client.
 */

import { describe, test, expect, jest, beforeEach } from '@jest/globals';

jest.mock('../../lib/db/db', () => ({
  query: jest.fn(),
  connect: jest.fn(),
}));

describe('withTransaction', () => {
  let mockDb: any;
  let client: any;

  beforeEach(() => {
    jest.resetModules();
    mockDb = require('../../lib/db/db');
    client = { query: jest.fn(async () => ({ rows: [] })), release: jest.fn() };
    mockDb.query = jest.fn();
    mockDb.connect = jest.fn(async () => client);
  });

  test('commits on the client that began the transaction and releases it', async () => {
    const { withTransaction } = await import('../../lib/db/with-transaction');

    const result = await withTransaction(async (tx) => {
      await tx.query('UPDATE t SET a = $1', [1]);
      return 'done';
    });

    expect(result).toBe('done');
    expect(client.query.mock.calls.map((c: any[]) => c[0])).toEqual(['BEGIN', 'UPDATE t SET a = $1', 'COMMIT']);
    // Nothing goes through the pool, where each statement could land on a different client.
    expect(mockDb.query).not.toHaveBeenCalled();
    expect(client.release).toHaveBeenCalledTimes(1);
    expect(client.release).toHaveBeenCalledWith(undefined);
  });

  test('rolls back, rethrows and still releases the client when the work fails', async () => {
    const { withTransaction } = await import('../../lib/db/with-transaction');

    await expect(
      withTransaction(async () => {
        throw new Error('boom');
      })
    ).rejects.toThrow('boom');

    expect(client.query.mock.calls.map((c: any[]) => c[0])).toEqual(['BEGIN', 'ROLLBACK']);
    expect(client.release).toHaveBeenCalledWith(undefined);
  });

  test('discards the client when the rollback itself fails', async () => {
    const { withTransaction } = await import('../../lib/db/with-transaction');
    const rollbackError = new Error('connection terminated');
    client.query = jest.fn(async (text: string) => {
      if (text === 'ROLLBACK') throw rollbackError;
      return { rows: [] };
    });

    await expect(
      withTransaction(async () => {
        throw new Error('boom');
      })
    ).rejects.toThrow('boom');

    // Releasing with an error makes the pool destroy the client instead of reusing it.
    expect(client.release).toHaveBeenCalledWith(rollbackError);
  });
});
