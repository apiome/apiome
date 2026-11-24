/**
 * What Browse does when the database cannot answer (DBP-1.27, #7210).
 *
 * Before this module a failed statement read as "no row", and a page that found no row rendered
 * **404** — so a full connection pool or a restarting database told crawlers that every page they
 * asked for was gone. Now a loader whose empty result means "not found" throws
 * {@link DatabaseUnavailableError} instead:
 *
 *   - a route handler answers {@link unavailableResponse} — `503` with `Retry-After`;
 *   - a page lets it reach the error boundary (`src/app/error.tsx`), which Next serves as `500`;
 *   - and `src/proxy.ts` answers `503` with `Retry-After` *before* rendering while the pool is
 *     saturated or a connection failure was just seen (`lib/db/availability.ts`).
 *
 * Lists that only decorate a page (home rails, an organization's products) keep their soft
 * fallback: they log and render empty.
 */

/** Seconds a client is asked to wait before retrying. */
export const RETRY_AFTER_SECONDS = 5;

/** The database could not answer: a failed connection, a full pool, a cancelled statement. */
export class DatabaseUnavailableError extends Error {
  /** The loader that failed (for logs; never shown to a visitor). */
  readonly scope: string;

  /**
   * @param scope - The loader that failed.
   * @param cause - What the pool rejected with.
   */
  constructor(scope: string, cause?: unknown) {
    super('The catalog database is temporarily unavailable.', { cause });
    this.name = 'DatabaseUnavailableError';
    this.scope = scope;
  }
}

/** What the `503` says. */
const UNAVAILABLE_TEXT = 'The catalog is temporarily unavailable. Try again shortly.';

/** The headers of every `503` Browse answers for the database. */
function unavailableHeaders(contentType: string): Record<string, string> {
  return {
    'Content-Type': contentType,
    'Retry-After': String(RETRY_AFTER_SECONDS),
    'Cache-Control': 'no-store',
  };
}

/**
 * The `503` a JSON API answers when the database is unavailable: a `{ detail }` body, the shape
 * the app's clients already read errors from.
 *
 * @returns A `503` JSON response with `Retry-After` that no cache may store.
 */
export function unavailableProblem(): Response {
  return new Response(JSON.stringify({ detail: UNAVAILABLE_TEXT }), {
    status: 503,
    headers: unavailableHeaders('application/json; charset=utf-8'),
  });
}

/**
 * The `503` a route handler answers when the database is unavailable.
 *
 * @param body - The plain-text body.
 * @returns A `503` response with `Retry-After` that no cache may store.
 */
export function unavailableResponse(body: string = UNAVAILABLE_TEXT): Response {
  return new Response(body, { status: 503, headers: unavailableHeaders('text/plain; charset=utf-8') });
}
