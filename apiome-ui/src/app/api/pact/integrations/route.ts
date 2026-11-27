/**
 * The Contracts landing's integrations list — PFX-8.1 (#7298).
 *
 * Proxies `GET /v1/tenants/{slug}/pact-integrations` with `q`, `filter` (`all`, `failing`, `stale`,
 * `bidirectional`, `mine`), `limit` (1–100) and `offset` (0–1000). Anything else, a repeated or empty
 * parameter, an unknown filter or an out-of-range page is a 400 naming it, without calling REST.
 * Permissions (`pacts:view`) and tenant scoping are REST's.
 */

import { NextRequest } from 'next/server';
import { integrationsProxyPath, integrationsQueryProblem } from '@lib/pact-overview';
import { forwardPactRead, pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  const search = request.nextUrl.searchParams;
  const problem = integrationsQueryProblem(search);
  if (problem) return pactError(400, problem);
  return forwardPactRead(integrationsProxyPath(search));
}
