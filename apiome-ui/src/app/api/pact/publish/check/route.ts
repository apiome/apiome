/**
 * **Check only** on the Publish page — PFX-8.3 (#7300).
 *
 * `GET ?consumer=&provider=&version=` reads the pact that consumer version already published for the
 * provider, as `GET /v1/tenants/{slug}/pact-broker/pacts/provider/{provider}/consumer/{consumer}/version/{version}`.
 * Names are passed as typed (REST resolves a handle, an id or a name), so a pact naming
 * “Billing Service” is found without guessing its handle. The page compares the answer with the file:
 * a 404 means the publish would be new. Nothing is written.
 *
 * Any other parameter, a missing, repeated or oversized one is a 400 naming it, without calling
 * REST. Permissions (`pacts:view`) and tenant scoping are REST's.
 */

import { NextRequest } from 'next/server';
import { pickCheckQuery } from '@lib/pact-publish-page';
import { pactProxyPath } from '@lib/pact-detail';
import { forwardPactRead, pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  const picked = pickCheckQuery(request.nextUrl.searchParams);
  if (!picked.ok) return pactError(400, picked.error);
  return forwardPactRead(pactProxyPath(picked.provider, picked.consumer, picked.version));
}
