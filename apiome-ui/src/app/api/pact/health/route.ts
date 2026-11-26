/**
 * The workspace's contract health — PFX-6.3 (#6955).
 *
 * Proxies `GET /v1/tenants/{slug}/pact-health` with `window` (`7d`, `30d`, `90d`), `provider`,
 * `consumer` and `state`. Anything else, a repeated or empty parameter, an unknown window or state, or
 * a malformed handle is a 400 naming it, without calling REST. Permissions (`pacts:view`) and tenant
 * scoping are REST's.
 */

import { NextRequest } from 'next/server';
import {
  HEALTH_PROXY_PATH,
  OVERVIEW_PARAMETERS,
  healthProxyPath,
  healthQueryProblem,
} from '@lib/pact-health';
import { forwardPactRead, pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  const search = request.nextUrl.searchParams;
  const problem = healthQueryProblem(search, OVERVIEW_PARAMETERS);
  if (problem) return pactError(400, problem);
  return forwardPactRead(healthProxyPath(HEALTH_PROXY_PATH, search, OVERVIEW_PARAMETERS));
}
