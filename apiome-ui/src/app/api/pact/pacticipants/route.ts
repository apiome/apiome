/**
 * The pacticipant list — PFX-5.1 (#6945); register one — PFX-8.10 (#7307).
 *
 * `GET` proxies `GET /v1/tenants/{slug}/pacticipants` with a page size of 50, forwarding `label`,
 * `state` (`deleted` lists what can still be restored) and `cursor`; any other parameter is a 400
 * naming it. `POST` registers a pacticipant (the New pacticipant dialog) with the fields
 * `checkCreateBody` knows; an unknown one is a 400 naming it. Permissions (`pacts:view`,
 * `pacts:create`), tenant scoping and a taken name (409) are REST's.
 */

import { NextRequest } from 'next/server';
import { LIST_FILTERS, PAGE_LIMIT } from '@lib/pact-pacticipants';
import { forwardPactList, forwardPactWrite, pactError } from '@lib/pact-proxy';
import { checkCreateBody } from '@lib/pact-pacticipant-settings';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  return forwardPactList(request.nextUrl.searchParams, 'pacticipants', LIST_FILTERS, PAGE_LIMIT);
}

export async function POST(request: NextRequest) {
  const checked = checkCreateBody(await request.json().catch(() => null));
  if (!checked.ok) return pactError(400, checked.error);
  return forwardPactWrite('pacticipants', 'POST', checked.body);
}
