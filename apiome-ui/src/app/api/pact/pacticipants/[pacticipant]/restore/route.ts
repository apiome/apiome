/**
 * Restore a deleted pacticipant — PFX-8.10 (#7307).
 *
 * Proxies `POST /v1/tenants/{slug}/pacticipants/{pacticipant}/restore` (no body): the Undo of the
 * Delete dialog and the **Restore** of the Pacticipants list's deleted view. A malformed handle is
 * a 404 without calling apiome-rest. Permissions (`pacts:delete`), tenant scoping, the grace
 * period and a handle taken since (409) are REST's.
 */

import { NextRequest } from 'next/server';
import { forwardPactWrite, pacticipantPath, pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function POST(
  _request: NextRequest,
  context: { params: Promise<{ pacticipant: string }> },
) {
  const { pacticipant } = await context.params;
  const path = pacticipantPath(pacticipant, 'restore');
  if (path === null) return pactError(404, 'Unknown pacticipant.');
  return forwardPactWrite(path, 'POST');
}
