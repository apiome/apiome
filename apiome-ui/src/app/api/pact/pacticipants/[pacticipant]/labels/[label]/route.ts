/**
 * One label of a pacticipant — PFX-8.10 (#7307).
 *
 * Proxies `PUT` (add; adding it again changes nothing) and `DELETE` (remove)
 * `/v1/tenants/{slug}/pacticipants/{pacticipant}/labels/{label}`, the Settings tab's label chips.
 * A malformed handle is a 404 and a label REST would refuse (empty, padded, over 255 characters,
 * control characters) a 400, both without calling apiome-rest. Permissions (`pacts:edit`) and
 * tenant scoping are REST's.
 */

import { NextRequest } from 'next/server';
import { forwardPactWrite, pacticipantPath, pactError } from '@lib/pact-proxy';
import { labelProblem } from '@lib/pact-pacticipant-settings';

export const dynamic = 'force-dynamic';

type Context = { params: Promise<{ pacticipant: string; label: string }> };

/** The REST path of the label, or the refusal. */
async function labelPath(
  context: Context,
): Promise<{ path: string } | { status: number; error: string }> {
  const { pacticipant, label } = await context.params;
  const problem = labelProblem(label, 'label');
  if (problem) return { status: 400, error: problem };
  const path = pacticipantPath(pacticipant, `labels/${encodeURIComponent(label)}`);
  return path === null ? { status: 404, error: 'Unknown pacticipant.' } : { path };
}

export async function PUT(_request: NextRequest, context: Context) {
  const target = await labelPath(context);
  if ('error' in target) return pactError(target.status, target.error);
  return forwardPactWrite(target.path, 'PUT');
}

export async function DELETE(_request: NextRequest, context: Context) {
  const target = await labelPath(context);
  if ('error' in target) return pactError(target.status, target.error);
  return forwardPactWrite(target.path, 'DELETE');
}
