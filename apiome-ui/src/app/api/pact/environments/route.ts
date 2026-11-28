/**
 * The workspace's broker environments — PFX-5.4 (#6948); create one — PFX-8.12 (#7309).
 *
 * `GET` proxies `GET /v1/tenants/{slug}/pact-broker/environments` (not paged) for the **Can I deploy**
 * environment picker, the matrix selector's environment choices and the Edit environment dialog. It
 * takes no parameters: any is a 400 naming it. `POST` creates an environment (the New environment
 * dialog — `apiome pact create-environment`) with the fields `checkEnvironmentBody` knows; an unknown
 * one is a 400 naming it. Permissions (`pacts:view`, `pacts:create`), tenant scoping and a taken name
 * (409) are REST's.
 */

import { NextRequest } from 'next/server';
import { ENVIRONMENTS_PROXY_PATH } from '@lib/pact-pacticipants';
import { forwardPactRead, forwardPactWrite, pactError } from '@lib/pact-proxy';
import { checkEnvironmentBody } from '@lib/pact-environment-writes';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  const [first] = [...request.nextUrl.searchParams.keys()];
  if (first !== undefined)
    return pactError(400, `Unsupported parameter ${first}: the environment list takes none.`);
  return forwardPactRead(ENVIRONMENTS_PROXY_PATH);
}

export async function POST(request: NextRequest) {
  const checked = checkEnvironmentBody(await request.json().catch(() => null));
  if (!checked.ok) return pactError(400, checked.error);
  return forwardPactWrite(ENVIRONMENTS_PROXY_PATH, 'POST', checked.body);
}
