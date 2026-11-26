/**
 * Acknowledge a re-publish request — PFX-6.2 (#6954).
 *
 * Proxies `POST /v1/tenants/{slug}/pact-republish-requests/{id}/acknowledge` with the body checked
 * by `pickAcknowledgeBody` (an optional `note` of at most 1000 characters; any other field is a 400
 * naming it). An id that is not a UUID is a 404 without calling REST. Permissions (`pacts:edit`),
 * tenant scoping and the closed-request refusal (409) are REST's.
 */

import { NextRequest } from 'next/server';
import { isRecordId, pickAcknowledgeBody, requestProxyPath } from '@lib/pact-remediation';
import { forwardPactWrite, pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function POST(request: NextRequest, context: { params: Promise<{ requestId: string }> }) {
  const { requestId } = await context.params;
  if (!isRecordId(requestId)) return pactError(404, 'Unknown re-publish request.');
  const picked = pickAcknowledgeBody(await request.json().catch(() => null));
  if (!picked.ok) return pactError(400, picked.error);
  return forwardPactWrite(requestProxyPath(requestId, 'acknowledge'), 'POST', picked.body);
}
