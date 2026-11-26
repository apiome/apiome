/**
 * One verification result with its log — PFX-5.5 (#6949).
 *
 * Proxies `GET /v1/tenants/{slug}/pact-verifier/pacts/provider/{p}/results/{id}`: the result, its
 * test results (expected and actual per mismatch) and, when the user may read verification
 * evidence, the evidence run. It takes no parameters: any is a 400 naming it; a malformed handle or
 * result id is a 404 without calling REST. Permissions (`pacts:view`, and
 * `verification_evidence:view` for the evidence) and tenant scoping are REST's.
 */

import { NextRequest } from 'next/server';
import { isPacticipantHandle } from '@lib/pact-pacticipants';
import { pickPactQuery } from '@lib/pact-detail';
import { isResultId, resultProxyPath } from '@lib/pact-verification';
import { forwardPactRead, pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ pacticipant: string; resultId: string }> },
) {
  const { pacticipant, resultId } = await context.params;
  if (!isPacticipantHandle(pacticipant)) return pactError(404, 'Unknown pacticipant.');
  if (!isResultId(resultId)) return pactError(404, 'Unknown verification result.');
  const picked = pickPactQuery(request.nextUrl.searchParams, false);
  if (!picked.ok) return pactError(400, picked.error);
  return forwardPactRead(resultProxyPath(pacticipant, resultId));
}
