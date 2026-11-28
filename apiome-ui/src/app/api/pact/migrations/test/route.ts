/**
 * Test the connection to a source broker — PFX-8.16 (#7313), the wizard's **Test connection**.
 *
 * `POST` proxies `POST /v1/tenants/{slug}/pact-migration/test`: REST signs in to the source with the
 * credentials given and counts its pacticipants. The body is checked by `checkSourceBody` (`source`,
 * `token` or `username` / `password`; anything else is a 400 naming it). Nothing is stored — the
 * credentials included. REST refuses a URL that is not a public http(s) address, and needs
 * `pacts:create` and `pacts:edit`.
 */

import { NextRequest } from 'next/server';
import { MIGRATION_PROXY_PATH, checkSourceBody } from '@lib/pact-migration';
import { forwardPactWrite, pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function POST(request: NextRequest) {
  const checked = checkSourceBody(await request.json().catch(() => null));
  if (!checked.ok) return pactError(400, checked.error);
  return forwardPactWrite(`${MIGRATION_PROXY_PATH}/test`, 'POST', checked.body);
}
