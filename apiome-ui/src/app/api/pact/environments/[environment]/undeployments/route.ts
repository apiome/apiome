/**
 * Record an undeployment from an environment — PFX-8.13 (#7310), the board's **Record an
 * undeployment** (`apiome pact record-undeployment`).
 *
 * `POST` takes `{ pacticipant, applicationInstance? }` (`checkUndeploymentBody`; anything else is a
 * 400 naming it). `recordUndeployment` finds what is currently deployed for the service and ends the
 * deployment in that instance — the unnamed one when none is given — as `pact-broker` does; nothing
 * matching is a 404 saying what is deployed. A name no environment can have is a 404 without calling
 * REST. Permissions (`pacts:edit`) and tenant scoping are REST's.
 */

import { NextRequest } from 'next/server';
import { environmentFromSegment, isEnvironmentName } from '@lib/pact-environments';
import { checkUndeploymentBody } from '@lib/pact-environment-endings';
import { recordUndeployment } from '@lib/pact-environment-writes-proxy';
import { answerWithRestCall, pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

type Context = { params: Promise<{ environment: string }> };

export async function POST(request: NextRequest, context: Context) {
  const name = environmentFromSegment((await context.params).environment);
  if (!isEnvironmentName(name)) return pactError(404, 'Unknown environment.');
  const checked = checkUndeploymentBody(await request.json().catch(() => null));
  if (!checked.ok) return pactError(400, checked.error);
  return answerWithRestCall((call) => recordUndeployment(call, name, checked.body));
}
