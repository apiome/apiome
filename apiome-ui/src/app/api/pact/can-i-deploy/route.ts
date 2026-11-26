/**
 * Can I deploy? — PFX-5.4 (#6948).
 *
 * Proxies `GET /v1/tenants/{slug}/pact-broker/can-i-deploy` for the **Can I deploy** page:
 * `pacticipant`, `version`, `toEnvironment` or `to`, and `ignore` (repeatable, at most 10). The
 * query is read with `parseCanIDeployQuery`: anything else, a missing or doubled destination, an
 * empty, repeated or oversized parameter is a 400 naming it. `Retry-After` comes back as
 * `retryAfterSeconds`. Permissions (`pacts:view`) and tenant scoping are REST's.
 */

import { NextRequest } from 'next/server';
import { CAN_I_DEPLOY_PROXY_PATH, canIDeployParams, parseCanIDeployQuery } from '@lib/pact-matrix';
import { forwardPactVerdict, pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  const parsed = parseCanIDeployQuery(request.nextUrl.searchParams);
  if (!parsed.ok) return pactError(400, parsed.error);
  const { query } = parsed;
  const params = canIDeployParams({
    pacticipant: query.pacticipant,
    version: query.version,
    kind: query.destination.kind,
    destination: query.destination.name,
    ignore: query.ignore,
  });
  return forwardPactVerdict(`${CAN_I_DEPLOY_PROXY_PATH}?${params.toString()}`);
}
