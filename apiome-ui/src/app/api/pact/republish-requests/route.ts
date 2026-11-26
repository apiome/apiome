/**
 * The workspace's re-publish requests — PFX-6.2 (#6954).
 *
 * Proxies `GET /v1/tenants/{slug}/pact-republish-requests` with `provider`, `consumer`, `state` (a
 * state or `open`) and `cursor`, 25 per page. Anything else, a repeated or empty parameter, a
 * malformed handle or cursor is a 400 naming it. Permissions (`pacts:view`) and tenant scoping are
 * REST's.
 */

import { NextRequest } from 'next/server';
import { requestQueryProblem, requestsListPath } from '@lib/pact-remediation';
import { forwardPactRead, pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  const search = request.nextUrl.searchParams;
  const problem = requestQueryProblem(search);
  if (problem) return pactError(400, problem);
  return forwardPactRead(requestsListPath(search));
}
