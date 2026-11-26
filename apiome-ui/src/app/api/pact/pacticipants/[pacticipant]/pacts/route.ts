/**
 * The integrations a pacticipant is in — PFX-5.2 (#6946).
 *
 * Proxies the broker matrix of one pacticipant (`GET /v1/tenants/{slug}/pact-broker/matrix` with
 * `q[][pacticipant]={handle}&latestby=cvp`), the rows the **Pacts** section of its page groups per
 * consumer and provider. It takes no parameters: any is a 400 naming it; a malformed handle is a
 * 404 without calling REST. Permissions (`pacts:view`) and tenant scoping are REST's.
 */

import { NextRequest } from 'next/server';
import { isPacticipantHandle } from '@lib/pact-pacticipants';
import { pacticipantPactsProxyPath, pickPactQuery } from '@lib/pact-detail';
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
  return forwardPactRead(pacticipantPactsProxyPath(pacticipant));
}
