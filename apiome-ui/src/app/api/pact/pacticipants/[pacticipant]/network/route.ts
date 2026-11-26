/**
 * A pacticipant's integration network — PFX-5.3 (#6947).
 *
 * Collects the group of pacticipants connected to one through pacts, reading each one's broker
 * matrix (`q[][pacticipant]={handle}&latestby=cvp`) as the signed-in user, 4 at a time and at most
 * 25 (see `collectPactNetwork`). It takes no parameters: any is a 400 naming it; a malformed handle
 * is a 404 without calling REST. Permissions (`pacts:view`) and tenant scoping are REST's: a
 * refusal of the pacticipant's own matrix keeps REST's status, a refusal of another one's is
 * reported on that pacticipant.
 */

import { NextRequest } from 'next/server';
import { isPacticipantHandle } from '@lib/pact-pacticipants';
import { pickPactQuery } from '@lib/pact-detail';
import { forwardPactNetwork, pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ pacticipant: string }> },
) {
  const { pacticipant } = await context.params;
  if (!isPacticipantHandle(pacticipant)) return pactError(404, 'Unknown pacticipant.');
  const picked = pickPactQuery(request.nextUrl.searchParams, false);
  if (!picked.ok) return pactError(400, picked.error);
  return forwardPactNetwork(pacticipant);
}
