/**
 * Verify every stale pact of a provider — PFX-5.5 (#6949).
 *
 * Proxies `POST /v1/tenants/{slug}/pact-verifier/pacts/provider/{p}/verify-stale`. It takes no
 * query parameters (any is a 400 naming it). The body is checked by `pickRunBody` with
 * `provider_version` required. A malformed handle is a 404 without calling REST. Permissions
 * (`pacts:create` and `verification_evidence:create`) and tenant scoping are REST's.
 */

import { NextRequest } from 'next/server';
import { isPacticipantHandle } from '@lib/pact-pacticipants';
import { pickPactQuery } from '@lib/pact-detail';
import { pickRunBody, verifyStaleProxyPath } from '@lib/pact-verification';
import { forwardPactRun, pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function POST(
  request: NextRequest,
  context: { params: Promise<{ pacticipant: string }> },
) {
  const { pacticipant } = await context.params;
  if (!isPacticipantHandle(pacticipant)) return pactError(404, 'Unknown pacticipant.');
  const query = pickPactQuery(request.nextUrl.searchParams, false);
  if (!query.ok) return pactError(400, query.error);
  const picked = pickRunBody(await request.json().catch(() => null), true);
  if (!picked.ok) return pactError(400, picked.error);
  return forwardPactRun(verifyStaleProxyPath(pacticipant), picked.body);
}
