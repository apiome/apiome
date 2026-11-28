/**
 * Recently deleted — PFX-8.14 (#7311), **Settings → Clean-up**.
 *
 * Proxies `GET /v1/tenants/{slug}/pact-retention/deleted`: deleted pacticipants and versions,
 * newest first, a fixed page size and `cursor` only (anything else is a 400 naming it). Restoring
 * goes through the pacticipant and version `…/restore` proxies. Permissions (`pacts:view`; restoring
 * needs `pacts:delete`) and tenant scoping are REST's.
 */

import { NextRequest } from 'next/server';
import { DELETED_PAGE_SIZE, DELETED_PROXY_PATH } from '@lib/pact-retention';
import { forwardPactList } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  return forwardPactList(request.nextUrl.searchParams, DELETED_PROXY_PATH, [], DELETED_PAGE_SIZE);
}
