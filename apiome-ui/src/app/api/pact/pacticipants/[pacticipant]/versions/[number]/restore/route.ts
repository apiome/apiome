/**
 * Restore a deleted version — PFX-8.11 (#7308).
 *
 * Proxies `POST /v1/tenants/{slug}/pacticipants/{pacticipant}/versions/{number}/restore` (no
 * body): the **Restore** of the Versions tab's Deleted view and the Undo after a delete. Its pacts,
 * verification results and deployments come back as they were. A malformed handle is a 404 and a
 * number that cannot be one path segment a 400, both without calling apiome-rest. Permissions
 * (`pacts:delete`), tenant scoping, the grace period and a number taken since (409) are REST's.
 */

import { NextRequest } from 'next/server';
import { forwardPactWrite, pacticipantPath, pactError } from '@lib/pact-proxy';
import { versionNumberProblem, versionProxyPath } from '@lib/pact-pacticipant-versions';

export const dynamic = 'force-dynamic';

export async function POST(
  _request: NextRequest,
  context: { params: Promise<{ pacticipant: string; number: string }> },
) {
  const { pacticipant, number } = await context.params;
  const problem = versionNumberProblem(number);
  if (problem) return pactError(400, problem);
  const path = versionProxyPath(pacticipantPath(pacticipant), number, 'restore');
  if (path === null) return pactError(404, 'Unknown pacticipant.');
  return forwardPactWrite(path, 'POST');
}
