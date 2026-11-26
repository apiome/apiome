/**
 * One pacticipant — PFX-5.1 (#6945).
 *
 * Proxies `GET /v1/tenants/{slug}/pacticipants/{pacticipant}`; a malformed handle is a 404 without
 * calling apiome-rest. Permissions (`pacts:view`) and tenant scoping are REST's.
 */

import { NextRequest } from 'next/server';
import { forwardPactRead, pacticipantPath, pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function GET(_request: NextRequest, context: { params: Promise<{ pacticipant: string }> }) {
  const { pacticipant } = await context.params;
  const path = pacticipantPath(pacticipant);
  if (path === null) return pactError(404, 'Unknown pacticipant.');
  return forwardPactRead(path);
}
