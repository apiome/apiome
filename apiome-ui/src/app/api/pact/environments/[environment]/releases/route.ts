/**
 * Record a release to an environment — PFX-8.12 (#7309), the Record a release dialog
 * (`apiome pact record-release`).
 *
 * `POST` takes `{ pacticipant, version }` (`checkRecordBody`; anything else is a 400 naming it) and
 * records it to the environment the segment names (`recordRelease` looks up its uuid). Releases do
 * not replace each other. A name no environment can have is a 404 without calling REST. Permissions
 * (`pacts:create`) and tenant scoping are REST's.
 */

import { NextRequest } from 'next/server';
import { environmentFromSegment, isEnvironmentName } from '@lib/pact-environments';
import { checkRecordBody } from '@lib/pact-environment-writes';
import { recordRelease } from '@lib/pact-environment-writes-proxy';
import { answerWithRestCall, pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

type Context = { params: Promise<{ environment: string }> };

export async function POST(request: NextRequest, context: Context) {
  const name = environmentFromSegment((await context.params).environment);
  if (!isEnvironmentName(name)) return pactError(404, 'Unknown environment.');
  const checked = checkRecordBody(await request.json().catch(() => null), 'release');
  if (!checked.ok) return pactError(400, checked.error);
  return answerWithRestCall((call) => recordRelease(call, name, checked.body));
}
