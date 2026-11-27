/**
 * A pacticipant's versions, latest recorded first — PFX-5.1 (#6945).
 *
 * Proxies `GET /v1/tenants/{slug}/pacticipants/{pacticipant}/versions` with a page size of 50,
 * forwarding `branch`, `tag`, `state` (`live` / `deleted`, PFX-8.11) and `cursor`; any other
 * parameter is a 400 naming it, a malformed
 * handle a 404. Permissions (`pacts:view`) and tenant scoping are REST's.
 */

import { NextRequest } from 'next/server';
import { PAGE_LIMIT, VERSION_FILTERS } from '@lib/pact-pacticipants';
import { forwardPactList, pacticipantPath, pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest, context: { params: Promise<{ pacticipant: string }> }) {
  const { pacticipant } = await context.params;
  const path = pacticipantPath(pacticipant, 'versions');
  if (path === null) return pactError(404, 'Unknown pacticipant.');
  return forwardPactList(request.nextUrl.searchParams, path, VERSION_FILTERS, PAGE_LIMIT);
}
