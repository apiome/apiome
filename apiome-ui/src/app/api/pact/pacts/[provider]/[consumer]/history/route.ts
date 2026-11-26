/**
 * An integration's history and verification results — PFX-5.2 (#6946).
 *
 * Proxies the broker matrix of the pair (`GET /v1/tenants/{slug}/pact-broker/matrix` with both
 * pacticipants, the newest 500 rows): every consumer version that published a pact for the
 * provider, with each verification result. It takes no parameters: any is a 400 naming it; a
 * malformed handle is a 404 without calling REST. Permissions (`pacts:view`) and tenant scoping
 * are REST's.
 */

import { NextRequest } from 'next/server';
import { pairHandles, pairHistoryProxyPath, pickPactQuery } from '@lib/pact-detail';
import { forwardPactRead, pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ provider: string; consumer: string }> },
) {
  const { provider, consumer } = await context.params;
  const pair = pairHandles(provider, consumer);
  if (pair === null) return pactError(404, 'Unknown pacticipant.');
  const picked = pickPactQuery(request.nextUrl.searchParams, false);
  if (!picked.ok) return pactError(400, picked.error);
  return forwardPactRead(pairHistoryProxyPath(pair.provider, pair.consumer));
}
