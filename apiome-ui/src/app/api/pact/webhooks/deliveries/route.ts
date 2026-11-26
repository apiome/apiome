/**
 * The webhook delivery log — PFX-5.6 (#6950).
 *
 * Proxies `GET /v1/tenants/{slug}/pact-webhook-deliveries` with a page of 25: `webhook` (a webhook
 * id) narrows to one webhook, `status` (`failure`, `retrying`, `not_run`, `success`) to one status,
 * `cursor` is the previous page's `nextCursor`. Any other, repeated, empty or malformed parameter is
 * a 400 naming it. The `pacts` permission (`view`) and tenant scoping are REST's.
 */

import { NextRequest } from 'next/server';
import { pickListQuery, withQuery } from '@lib/pact-pacticipants';
import { DELIVERIES_PROXY_PATH, DELIVERY_FILTERS, DELIVERY_PAGE, deliveryQueryProblem } from '@lib/pact-webhooks';
import { forwardPactRead, pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  const picked = pickListQuery(request.nextUrl.searchParams, DELIVERY_FILTERS);
  if (!picked.ok) return pactError(400, picked.error);
  const problem = deliveryQueryProblem(picked.query);
  if (problem) return pactError(400, problem);
  return forwardPactRead(withQuery(DELIVERIES_PROXY_PATH, picked.query, DELIVERY_PAGE));
}
