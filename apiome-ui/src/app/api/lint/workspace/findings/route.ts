/**
 * GET /api/lint/workspace/findings — cross-catalog findings queue (CLX-4.1, #4859).
 * Forwards whitelisted filter/sort/pagination params to apiome-rest.
 */
import { NextRequest } from 'next/server';
import { proxyToRest, requireSessionUser, whitelistedQuery } from '../proxy';

export async function GET(request: NextRequest) {
  const auth = await requireSessionUser();
  if ('error' in auth) return auth.error;
  const query = whitelistedQuery(request.nextUrl.searchParams);
  return proxyToRest(auth.user, `/lint/workspace/findings${query}`);
}
