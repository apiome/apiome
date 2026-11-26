/**
 * The deploy simulator — PFX-5.7 (#6951).
 *
 * Proxies `GET /v1/tenants/{slug}/pact-environments/{name}/simulate`: `pacticipant` and `version`
 * (required) name the version to deploy, `applicationInstance` (optional) the instance. It records
 * nothing. Any other, repeated, empty or over-long parameter, or a missing one, is a 400 naming it;
 * a name no environment can have is a 404 without calling REST. The `pacts` permission (`view`) and
 * tenant scoping are REST's.
 */

import { NextRequest } from 'next/server';
import { environmentFromSegment, isEnvironmentName, pickSimulationQuery, simulateProxyPath } from '@lib/pact-environments';
import { forwardPactRead, pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

type Context = { params: Promise<{ environment: string }> };

export async function GET(request: NextRequest, context: Context) {
  const environment = environmentFromSegment((await context.params).environment);
  if (!isEnvironmentName(environment)) return pactError(404, 'Unknown environment.');
  const picked = pickSimulationQuery(request.nextUrl.searchParams);
  if (!picked.ok) return pactError(400, picked.error);
  return forwardPactRead(`${simulateProxyPath(environment)}?${picked.query.toString()}`);
}
