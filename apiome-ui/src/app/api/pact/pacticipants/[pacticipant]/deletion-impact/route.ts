/**
 * What deleting a pacticipant takes with it — PFX-8.10 (#7307).
 *
 * Proxies `GET /v1/tenants/{slug}/pacticipants/{pacticipant}/deletion-impact`: the counts, the
 * providers and consumers that lose it, the versions that block the delete, and the grace period.
 * A malformed handle is a 404 without calling apiome-rest. Permissions (`pacts:view`) and tenant
 * scoping are REST's.
 */

import { NextRequest } from 'next/server';
import { forwardPactRead, pacticipantPath, pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function GET(
  _request: NextRequest,
  context: { params: Promise<{ pacticipant: string }> },
) {
  const { pacticipant } = await context.params;
  const path = pacticipantPath(pacticipant, 'deletion-impact');
  if (path === null) return pactError(404, 'Unknown pacticipant.');
  return forwardPactRead(path);
}
