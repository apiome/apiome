/**
 * End support for a release in an environment — PFX-8.13 (#7310), the board's **End support** and
 * the Record a release dialog's unticked releases (`apiome pact record-support-ended`).
 *
 * `POST` takes `{ pacticipant, version }` (`checkSupportEndedBody`; anything else is a 400 naming it).
 * `recordSupportEnded` finds that version's supported release there and ends it; a version not
 * released there is a 404. A name no environment can have is a 404 without calling REST. Permissions
 * (`pacts:edit`) and tenant scoping are REST's.
 */

import { NextRequest } from 'next/server';
import { environmentFromSegment, isEnvironmentName } from '@lib/pact-environments';
import { checkSupportEndedBody } from '@lib/pact-environment-endings';
import { recordSupportEnded } from '@lib/pact-environment-writes-proxy';
import { answerWithRestCall, pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

type Context = { params: Promise<{ environment: string }> };

export async function POST(request: NextRequest, context: Context) {
  const name = environmentFromSegment((await context.params).environment);
  if (!isEnvironmentName(name)) return pactError(404, 'Unknown environment.');
  const checked = checkSupportEndedBody(await request.json().catch(() => null));
  if (!checked.ok) return pactError(400, checked.error);
  return answerWithRestCall((call) => recordSupportEnded(call, name, checked.body));
}
