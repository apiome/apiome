/**
 * Errors the search runner raises on purpose (DBP-1.16, #7199).
 *
 * Kept out of `lib/db/search.ts`: that file is a `'use server'` module, which may only export
 * async functions.
 */

/** A search or suggestion statement ran past the pool's `statement_timeout` and was cancelled. */
export class SearchTimeoutError extends Error {
  constructor() {
    super('The search took too long and was stopped. Try a narrower query.');
    this.name = 'SearchTimeoutError';
  }
}
