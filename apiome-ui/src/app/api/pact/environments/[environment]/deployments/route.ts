/**
 * An environment's deployment history — PFX-5.7 (#6951).
 *
 * Proxies `GET /v1/tenants/{slug}/pact-environments/{name}/deployments` with a page of 25:
 * `pacticipant` (a handle or name) narrows to one pacticipant, `cursor` is the previous page's
 * `nextCursor`. Any other, repeated, empty or malformed parameter is a 400 naming it; a name no
 * environment can have is a 404 without calling REST. The `pacts` permission (`view`) and tenant
 * scoping are REST's.
 *
 * `POST` records a deployment — PFX-8.12 (#7309), the Record a deployment dialog
 * (`apiome pact record-deployment`): `{ pacticipant, version, applicationInstance?, recordAnyway? }`
 * (`checkRecordBody`; anything else is a 400 naming it). `recordDeployment` asks can-i-deploy first
 * and refuses a "no" with a 409 and its reasons unless `recordAnyway` is true; an override is sent
 * to REST as `overrideCanIDeploy=true`, which the audit row records. `pacts:create` is REST's.
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
import { answerWithRestCall, forwardPactRead, pactError } from '@lib/pact-proxy';
import { checkRecordBody } from '@lib/pact-environment-writes';
import { recordDeployment } from '@lib/pact-environment-writes-proxy';

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

export async function POST(request: NextRequest, context: Context) {
  const environment = environmentFromSegment((await context.params).environment);
  if (!isEnvironmentName(environment)) return pactError(404, 'Unknown environment.');
  const checked = checkRecordBody(await request.json().catch(() => null), 'deployment');
  if (!checked.ok) return pactError(400, checked.error);
  return answerWithRestCall((call) => recordDeployment(call, environment, checked.body));
}
