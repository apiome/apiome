/**
 * The pacticipant list — PFX-5.1 (#6945).
 *
 * Proxies `GET /v1/tenants/{slug}/pacticipants` with a page size of 50, forwarding `label` and
 * `cursor`; any other parameter is a 400 naming it. Permissions (`pacts:view`) and tenant scoping
 * are REST's.
 */

import { NextRequest } from 'next/server';
import { LIST_FILTERS, PAGE_LIMIT } from '@lib/pact-pacticipants';
import { forwardPactList } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  return forwardPactList(request.nextUrl.searchParams, 'pacticipants', LIST_FILTERS, PAGE_LIMIT);
}
