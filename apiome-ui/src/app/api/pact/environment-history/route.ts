/**
 * The environments' history — PFX-8.13 (#7310).
 *
 * Proxies `GET /v1/tenants/{slug}/pact-environments/history` for the **Environments** page's History
 * view: deployed, undeployed, released and support-ended events, newest first. `environment`,
 * `pacticipant` and `cursor` are optional (`pickEventsQuery`; anything else, repeated or empty is a
 * 400 naming it); the page size is fixed here. Permissions (`pacts:view`) and tenant scoping are
 * REST's.
 */

import { NextRequest } from 'next/server';
import { EVENTS_PROXY_PATH, pickEventsQuery } from '@lib/pact-environment-board';
import { forwardPactRead, pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  const picked = pickEventsQuery(request.nextUrl.searchParams);
  if (!picked.ok) return pactError(400, picked.error);
  return forwardPactRead(`${EVENTS_PROXY_PATH}?${picked.query.toString()}`);
}
