/**
 * The previous different pact of a consumer version — PFX-5.2 (#6946).
 *
 * The Pact Broker's `…/version/{v}/previous-distinct`, which Apiome's broker does not serve: the
 * proxy reads the pact (`version`, or the latest), the integration's history, and earlier pacts
 * until one's content differs (at most 20), all as the signed-in user. It answers the outcome
 * (`found`, `first`, `unchanged`, `scan-limit`, `not-in-history`) and the previous pact when
 * found; a read that fails is REST's status and message, never "no previous pact". `version` is
 * the only parameter (refused with the reason otherwise); a malformed handle is a 404 without
 * calling REST. Permissions (`pacts:view`) and tenant scoping are REST's.
 */

import { NextRequest } from 'next/server';
import { pairHandles, pickPactQuery } from '@lib/pact-detail';
import { forwardPreviousPact, pactError } from '@lib/pact-proxy';

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
  return forwardPreviousPact(pair.provider, pair.consumer, picked.version);
}
