/**
 * A provider's verification history — PFX-5.5 (#6949).
 *
 * Proxies `GET /v1/tenants/{slug}/pact-verifier/pacts/provider/{p}/results`, newest first, 25 a
 * page. It accepts `consumer` (a pacticipant handle) and `cursor` (the previous page's
 * `next_cursor`); anything else, a repeat, an empty value or a malformed one is a 400 naming it.
 * A malformed handle is a 404 without calling REST. Permissions (`pacts:view`) and tenant scoping
 * are REST's.
 */

import { NextRequest } from 'next/server';
import { isPacticipantHandle } from '@lib/pact-pacticipants';
import { HISTORY_FILTERS, HISTORY_PAGE, historyQueryProblem, resultsProxyPath } from '@lib/pact-verification';
import { forwardPactList, pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ pacticipant: string }> },
) {
  const { pacticipant } = await context.params;
  if (!isPacticipantHandle(pacticipant)) return pactError(404, 'Unknown pacticipant.');
  const search = request.nextUrl.searchParams;
  const problem = historyQueryProblem(search);
  if (problem) return pactError(400, problem);
  return forwardPactList(search, resultsProxyPath(pacticipant), HISTORY_FILTERS, HISTORY_PAGE);
}
