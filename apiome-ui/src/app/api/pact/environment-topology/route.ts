/**
 * The workspace's environments and what is in each now — PFX-5.7 (#6951).
 *
 * Proxies `GET /v1/tenants/{slug}/pact-environments` (not paged; `truncated` past 2000 entries) for
 * the **Environments** dashboard and an environment's page. It takes no parameters: any is a 400
 * naming it. Permissions (`pacts:view`) and tenant scoping are REST's.
 */

import { NextRequest } from 'next/server';
import { TOPOLOGY_PROXY_PATH } from '@lib/pact-environments';
import { forwardPactRead, pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  const [first] = [...request.nextUrl.searchParams.keys()];
  if (first !== undefined) return pactError(400, `Unsupported parameter ${first}: the environment topology takes none.`);
  return forwardPactRead(TOPOLOGY_PROXY_PATH);
}
