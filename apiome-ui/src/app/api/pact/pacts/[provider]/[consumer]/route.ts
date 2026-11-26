/**
 * One pact of an integration — PFX-5.2 (#6946).
 *
 * Proxies `GET /v1/tenants/{slug}/pact-broker/pacts/provider/{provider}/consumer/{consumer}/version/{version}`,
 * or `…/latest` without `version`. `version` is the only parameter: any other, an empty, repeated
 * or oversized one, or one containing `/` is a 400 naming the problem; a malformed handle is a 404
 * without calling REST. Permissions (`pacts:view`) and tenant scoping are REST's.
 */

import { NextRequest } from 'next/server';
import { pactProxyPath, pairHandles, pickPactQuery } from '@lib/pact-detail';
import { forwardPactRead, pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ provider: string; consumer: string }> },
) {
  const { provider, consumer } = await context.params;
  const pair = pairHandles(provider, consumer);
  if (pair === null) return pactError(404, 'Unknown pacticipant.');
  const picked = pickPactQuery(request.nextUrl.searchParams, true);
  if (!picked.ok) return pactError(400, picked.error);
  return forwardPactRead(pactProxyPath(pair.provider, pair.consumer, picked.version));
}
