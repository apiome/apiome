/**
 * Load shedding for the Browse site (DBP-1.27, #7210).
 *
 * Runs before every page and route handler. While the database pool is saturated, or a connection
 * failure was seen in the last few seconds, the request is answered `503` with `Retry-After`
 * instead of being rendered: a crawler backs off and retries, where a page rendered without its
 * data used to answer `404` and be dropped from the index. The decision is
 * `lib/db/availability.ts`; this file only turns it into a response.
 *
 * Static assets are not matched — they need no database.
 */

import { NextResponse } from 'next/server';
import { shedReason } from '../lib/db/availability';
import { RETRY_AFTER_SECONDS } from '../lib/db/errors';

/**
 * Refuse the request when the database cannot take it.
 *
 * @returns A `503` response, or nothing to let the request through.
 */
export function proxy(): NextResponse | undefined {
  const reason = shedReason();
  if (!reason) return undefined;
  return new NextResponse('The catalog is temporarily unavailable. Try again shortly.', {
    status: 503,
    headers: {
      'Content-Type': 'text/plain; charset=utf-8',
      'Retry-After': String(RETRY_AFTER_SECONDS),
      'Cache-Control': 'no-store',
      'X-Apiome-Shed': reason,
    },
  });
}

export const config = {
  matcher: ['/((?!_next/static|_next/image|favicon.ico|.*\\.(?:png|svg|ico|jpg|jpeg|gif|webp|woff2?|css|js|map)$).*)'],
};
