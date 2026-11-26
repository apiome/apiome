/**
 * One consumer ↔ provider pair's contract health and trend — PFX-6.3 (#6955).
 *
 * Proxies `GET /v1/tenants/{slug}/pact-health/providers/{provider}/consumers/{consumer}` with
 * `window` (`7d`, `30d`, `90d`) only: anything else, a repeated or empty parameter or an unknown
 * window is a 400 naming it. A provider or consumer that is not a pacticipant handle is a 404 without
 * calling REST. Permissions (`pacts:view`) and tenant scoping are REST's.
 */

import { NextRequest } from 'next/server';
import { isPacticipantHandle } from '@lib/pact-pacticipants';
import { healthProxyPath, healthQueryProblem, pairHealthProxyPath } from '@lib/pact-health';
import { forwardPactRead, pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

/** The pair read takes only the window. */
const PAIR_PARAMETERS = ['window'] as const;

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ provider: string; consumer: string }> },
) {
  const { provider, consumer } = await context.params;
  if (!isPacticipantHandle(provider) || !isPacticipantHandle(consumer)) {
    return pactError(404, 'Unknown pacticipant.');
  }
  const search = request.nextUrl.searchParams;
  const problem = healthQueryProblem(search, PAIR_PARAMETERS);
  if (problem) return pactError(400, problem);
  return forwardPactRead(
    healthProxyPath(pairHealthProxyPath(provider, consumer), search, PAIR_PARAMETERS),
  );
}
