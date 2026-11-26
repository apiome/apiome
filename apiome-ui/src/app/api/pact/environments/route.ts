/**
 * The workspace's broker environments — PFX-5.4 (#6948).
 *
 * Proxies `GET /v1/tenants/{slug}/pact-broker/environments` (not paged) for the **Can I deploy**
 * environment picker and the matrix selector's environment choices. It takes no parameters: any is
 * a 400 naming it. Permissions (`pacts:view`) and tenant scoping are REST's.
 */

import { NextRequest } from 'next/server';
import { ENVIRONMENTS_PROXY_PATH } from '@lib/pact-pacticipants';
import { forwardPactRead, pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  const [first] = [...request.nextUrl.searchParams.keys()];
  if (first !== undefined)
    return pactError(400, `Unsupported parameter ${first}: the environment list takes none.`);
  return forwardPactRead(ENVIRONMENTS_PROXY_PATH);
}
