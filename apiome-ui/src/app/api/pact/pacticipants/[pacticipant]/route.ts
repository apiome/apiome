/**
 * One pacticipant — PFX-5.1 (#6945); edit and delete — PFX-8.10 (#7307).
 *
 * Proxies `GET`, `PATCH` and `DELETE /v1/tenants/{slug}/pacticipants/{pacticipant}`; a malformed
 * handle is a 404 without calling apiome-rest. `PATCH` forwards only the fields
 * `checkPatchBody` knows (an unknown one is a 400 naming it); `DELETE` forwards a `reason` of at
 * most 500 characters and nothing else. Permissions (`pacts:view`, `pacts:edit`, `pacts:delete`),
 * tenant scoping, the rename collision (409) and the in-use refusal (409) are REST's.
 */

import { NextRequest } from 'next/server';
import { forwardPactRead, forwardPactWrite, pacticipantPath, pactError } from '@lib/pact-proxy';
import { checkPatchBody, checkReason } from '@lib/pact-pacticipant-settings';

export const dynamic = 'force-dynamic';

type Context = { params: Promise<{ pacticipant: string }> };

/** The REST path of the pacticipant in the route, or `null` for a malformed handle. */
async function path(context: Context): Promise<string | null> {
  const { pacticipant } = await context.params;
  return pacticipantPath(pacticipant);
}

export async function GET(_request: NextRequest, context: Context) {
  const target = await path(context);
  if (target === null) return pactError(404, 'Unknown pacticipant.');
  return forwardPactRead(target);
}

export async function PATCH(request: NextRequest, context: Context) {
  const target = await path(context);
  if (target === null) return pactError(404, 'Unknown pacticipant.');
  const checked = checkPatchBody(await request.json().catch(() => null));
  if (!checked.ok) return pactError(400, checked.error);
  return forwardPactWrite(target, 'PATCH', checked.body);
}

export async function DELETE(request: NextRequest, context: Context) {
  const target = await path(context);
  if (target === null) return pactError(404, 'Unknown pacticipant.');
  const params = request.nextUrl.searchParams;
  const unknown = [...params.keys()].filter((key) => key !== 'reason');
  if (unknown.length) return pactError(400, `Unknown parameter: ${unknown.join(', ')}. Send only reason.`);
  const reason = checkReason(params.get('reason'));
  if (!reason.ok) return pactError(400, reason.error);
  const query = reason.body ? `?reason=${encodeURIComponent(reason.body)}` : '';
  return forwardPactWrite(`${target}${query}`, 'DELETE');
}
