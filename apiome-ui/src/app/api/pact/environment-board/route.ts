/**
 * The what-is-where board — PFX-8.13 (#7310).
 *
 * Proxies `GET /v1/tenants/{slug}/pact-environments/board` for the **Environments** page's Board view:
 * pacticipants × environments, each running version with its verdict and whether the next version
 * can go. It takes no parameters: any is a 400 naming it. Permissions (`pacts:view`) and tenant
 * scoping are REST's.
 */

import { NextRequest } from 'next/server';
import { BOARD_PROXY_PATH } from '@lib/pact-environment-board';
import { forwardPactRead, pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  const [first] = [...request.nextUrl.searchParams.keys()];
  if (first !== undefined) return pactError(400, `Unsupported parameter ${first}: the board takes none.`);
  return forwardPactRead(BOARD_PROXY_PATH);
}
