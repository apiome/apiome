/**
 * Where a provider's verification stands — PFX-5.5 (#6949).
 *
 * Proxies `GET /v1/tenants/{slug}/pact-verifier/pacts/provider/{p}/verification-status`: each
 * consumer's newest pact, its newest result, whether it is stale, and the KPI counts. It takes no
 * parameters: any is a 400 naming it; a malformed handle is a 404 without calling REST.
 * Permissions (`pacts:view`) and tenant scoping are REST's.
 */

import { NextRequest } from 'next/server';
import { isPacticipantHandle } from '@lib/pact-pacticipants';
import { pickPactQuery } from '@lib/pact-detail';
import { statusProxyPath } from '@lib/pact-verification';
import { forwardPactRead, pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ pacticipant: string }> },
) {
  const { pacticipant } = await context.params;
  if (!isPacticipantHandle(pacticipant)) return pactError(404, 'Unknown pacticipant.');
  const picked = pickPactQuery(request.nextUrl.searchParams, false);
  if (!picked.ok) return pactError(400, picked.error);
  return forwardPactRead(statusProxyPath(pacticipant));
}
