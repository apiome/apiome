/**
 * One version of a pacticipant — PFX-8.11 (#7308).
 *
 * Proxies `GET` (read it, for the Versions tab's Deployed and Unverified views) and `DELETE`
 * (soft-delete it with its pacts and results) `/v1/tenants/{slug}/pacticipants/{pacticipant}/
 * versions/{number}`. `DELETE` forwards a `reason` of at most 500 characters and nothing else:
 * `force` is refused by name, so a deployed version is never deleted from the UI (REST answers
 * `409 pacticipant-version-in-use`). A malformed handle is a 404 and a number that cannot be one
 * path segment a 400, both without calling apiome-rest. Permissions (`pacts:view`, `pacts:delete`)
 * and tenant scoping are REST's.
 */

import { NextRequest } from 'next/server';
import { forwardPactRead, forwardPactWrite, pacticipantPath, pactError } from '@lib/pact-proxy';
import { checkReason } from '@lib/pact-pacticipant-settings';
import { versionNumberProblem, versionProxyPath } from '@lib/pact-pacticipant-versions';

export const dynamic = 'force-dynamic';

type Context = { params: Promise<{ pacticipant: string; number: string }> };

/** The REST path of the version in the route, or the refusal. */
async function target(context: Context): Promise<{ path: string } | { status: number; error: string }> {
  const { pacticipant, number } = await context.params;
  const problem = versionNumberProblem(number);
  if (problem) return { status: 400, error: problem };
  const path = versionProxyPath(pacticipantPath(pacticipant), number);
  return path === null ? { status: 404, error: 'Unknown pacticipant.' } : { path };
}

export async function GET(_request: NextRequest, context: Context) {
  const found = await target(context);
  if ('error' in found) return pactError(found.status, found.error);
  return forwardPactRead(found.path);
}

export async function DELETE(request: NextRequest, context: Context) {
  const found = await target(context);
  if ('error' in found) return pactError(found.status, found.error);
  const params = request.nextUrl.searchParams;
  if (params.has('force')) {
    return pactError(400, 'force is not accepted: record the version’s undeployment first, then delete it.');
  }
  const unknown = [...params.keys()].filter((key) => key !== 'reason');
  if (unknown.length) return pactError(400, `Unknown parameter: ${unknown.join(', ')}. Send only reason.`);
  if (params.getAll('reason').length > 1) return pactError(400, 'The reason parameter is given more than once.');
  const reason = checkReason(params.get('reason'));
  if (!reason.ok) return pactError(400, reason.error);
  const query = reason.body ? `?reason=${encodeURIComponent(reason.body)}` : '';
  return forwardPactWrite(`${found.path}${query}`, 'DELETE');
}
