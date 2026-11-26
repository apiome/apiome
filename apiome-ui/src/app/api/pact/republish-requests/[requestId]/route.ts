/**
 * One re-publish request — PFX-6.2 (#6954).
 *
 * Proxies `GET /v1/tenants/{slug}/pact-republish-requests/{id}` (no parameters: any is a 400 naming
 * it). An id that is not a UUID is a 404 without calling REST. Permissions (`pacts:view`) and tenant
 * scoping are REST's.
 */

import { NextRequest } from 'next/server';
import { pickPactQuery } from '@lib/pact-detail';
import { isRecordId, requestProxyPath } from '@lib/pact-remediation';
import { forwardPactRead, pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest, context: { params: Promise<{ requestId: string }> }) {
  const { requestId } = await context.params;
  if (!isRecordId(requestId)) return pactError(404, 'Unknown re-publish request.');
  const picked = pickPactQuery(request.nextUrl.searchParams, false);
  if (!picked.ok) return pactError(400, picked.error);
  return forwardPactRead(requestProxyPath(requestId));
}
