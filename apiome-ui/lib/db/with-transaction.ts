/**
 * Run a transaction on one pooled client.
 *
 * `pool.query()` checks a client out for a single statement and puts it straight back, so
 * `pool.query('BEGIN')` followed by more `pool.query()` calls does not make a transaction: under
 * concurrent requests the statements land on different clients, the `BEGIN` leaves its client in
 * an open transaction, and whatever unrelated request picks that client up next runs inside it —
 * holding its row locks until some `COMMIT` or `ROLLBACK` happens to reach the same client. Every
 * statement of a transaction has to run on the client that began it.
 */

// `./db` exports the pool with `module.exports`, like the other lib/db consumers it is `require`d.
// eslint-disable-next-line @typescript-eslint/no-require-imports
const connectionPool = require('./db');

/** The client a transaction's statements run on. */
export type TransactionClient = {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  query: (text: string, params?: any[]) => Promise<any>;
};

/**
 * Check out one client, run `work` between `BEGIN` and `COMMIT` on it, and release it.
 *
 * @param work The statements of the transaction. They must go through the client it is given.
 * @returns Whatever `work` returns, once the transaction has committed.
 * @throws Whatever `work` throws, after the transaction has been rolled back.
 */
export async function withTransaction<T>(work: (client: TransactionClient) => Promise<T>): Promise<T> {
  const client = await connectionPool.connect();
  let unusable: Error | undefined;
  try {
    await client.query('BEGIN');
    const result = await work(client);
    await client.query('COMMIT');
    return result;
  } catch (error) {
    try {
      await client.query('ROLLBACK');
    } catch (rollbackError) {
      // The transaction could not be ended, so the client must not go back into the pool.
      unusable = rollbackError instanceof Error ? rollbackError : new Error(String(rollbackError));
    }
    throw error;
  } finally {
    client.release(unusable);
  }
}
