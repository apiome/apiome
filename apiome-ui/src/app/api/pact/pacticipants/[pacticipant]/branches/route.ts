/**
 * A pacticipant's branches, by name, each with its head version — PFX-5.1 (#6945).
 *
 * Proxies `GET /v1/tenants/{slug}/pacticipants/{pacticipant}/branches` with a page size of 100,
 * forwarding `cursor`; any other parameter is a 400 naming it, a malformed handle a 404.
 * Permissions (`pacts:view`) and tenant scoping are REST's.
 */

import { NextRequest } from 'next/server';
import { LONG_PAGE_LIMIT } from '@lib/pact-pacticipants';
import { forwardPactList, pacticipantPath, pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest, context: { params: Promise<{ pacticipant: string }> }) {
  const { pacticipant } = await context.params;
  const path = pacticipantPath(pacticipant, 'branches');
  if (path === null) return pactError(404, 'Unknown pacticipant.');
  return forwardPactList(request.nextUrl.searchParams, path, [], LONG_PAGE_LIMIT);
}
