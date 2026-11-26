/**
 * An environment's deployment history — PFX-5.7 (#6951).
 *
 * Proxies `GET /v1/tenants/{slug}/pact-environments/{name}/deployments` with a page of 25:
 * `pacticipant` (a handle or name) narrows to one pacticipant, `cursor` is the previous page's
 * `nextCursor`. Any other, repeated, empty or malformed parameter is a 400 naming it; a name no
 * environment can have is a 404 without calling REST. The `pacts` permission (`view`) and tenant
 * scoping are REST's.
 */

import { NextRequest } from 'next/server';
import { pickListQuery, withQuery } from '@lib/pact-pacticipants';
import {
  HISTORY_FILTERS,
  HISTORY_PAGE,
  historyProxyPath,
  historyQueryProblem,
  environmentFromSegment,
  isEnvironmentName,
} from '@lib/pact-environments';
import { forwardPactRead, pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

type Context = { params: Promise<{ environment: string }> };

export async function GET(request: NextRequest, context: Context) {
  const environment = environmentFromSegment((await context.params).environment);
  if (!isEnvironmentName(environment)) return pactError(404, 'Unknown environment.');
  const picked = pickListQuery(request.nextUrl.searchParams, HISTORY_FILTERS);
  if (!picked.ok) return pactError(400, picked.error);
  const problem = historyQueryProblem(picked.query);
  if (problem) return pactError(400, problem);
  return forwardPactRead(withQuery(historyProxyPath(environment), picked.query, HISTORY_PAGE));
}
