/**
 * What each environment runs of one pacticipant — PFX-5.1 (#6945).
 *
 * Reads `GET /v1/tenants/{slug}/pact-broker/environments`, then each environment's
 * `…/deployed-versions/currently-deployed?pacticipant=` and `…/released-versions/currently-supported?
 * pacticipant=`, and answers `{ environments }`. An environment whose lists cannot be read carries
 * the reason in `error`; a refused environment list keeps REST's status. A malformed handle is a
 * 404 without calling apiome-rest. Permissions (`pacts:view`) and tenant scoping are REST's.
 */

import { NextRequest } from 'next/server';
import { isPacticipantHandle } from '@lib/pact-pacticipants';
import { forwardPacticipantEnvironments, pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function GET(_request: NextRequest, context: { params: Promise<{ pacticipant: string }> }) {
  const { pacticipant } = await context.params;
  if (!isPacticipantHandle(pacticipant)) return pactError(404, 'Unknown pacticipant.');
  return forwardPacticipantEnvironments(pacticipant);
}
