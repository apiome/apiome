/**
 * Edit or delete one environment — PFX-8.12 (#7309), from the Environments page's column menu.
 *
 * The segment is the environment's name; the handlers in `@lib/pact-environment-writes-proxy` look
 * up its uuid. `PUT` replaces every field (`checkEnvironmentBody`; it may rename it). `DELETE` is
 * refused with a 409 while any version is deployed or released there, and takes no parameters (any
 * is a 400 naming it). A name no environment can have is a 404 without calling REST. Permissions
 * (`pacts:edit`, `pacts:delete`) and tenant scoping are REST's.
 */

import { NextRequest } from 'next/server';
import { environmentFromSegment, isEnvironmentName } from '@lib/pact-environments';
import { checkEnvironmentBody } from '@lib/pact-environment-writes';
import { deleteEnvironment, updateEnvironment } from '@lib/pact-environment-writes-proxy';
import { answerWithRestCall, pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

type Context = { params: Promise<{ environment: string }> };

/** The environment's name from the route, or `null` when no environment could have it. */
async function nameOf(context: Context): Promise<string | null> {
  const name = environmentFromSegment((await context.params).environment);
  return isEnvironmentName(name) ? name : null;
}

export async function PUT(request: NextRequest, context: Context) {
  const name = await nameOf(context);
  if (name === null) return pactError(404, 'Unknown environment.');
  const checked = checkEnvironmentBody(await request.json().catch(() => null));
  if (!checked.ok) return pactError(400, checked.error);
  return answerWithRestCall((call) => updateEnvironment(call, name, checked.body));
}

export async function DELETE(request: NextRequest, context: Context) {
  const name = await nameOf(context);
  if (name === null) return pactError(404, 'Unknown environment.');
  const [first] = [...request.nextUrl.searchParams.keys()];
  if (first !== undefined) return pactError(400, `Unsupported parameter ${first}: deleting an environment takes none.`);
  return answerWithRestCall((call) => deleteEnvironment(call, name));
}
