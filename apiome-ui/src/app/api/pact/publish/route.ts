/**
 * Publish a pact to the broker — PFX-5.8 (#6952).
 *
 * `POST` takes `{ consumerName, providerName, version, branch?, tags?, buildUrl?, pact }` (the Pact
 * document as text) from the Import-a-Pact-file dialog and forwards it as
 * `POST /v1/tenants/{slug}/pact-broker/contracts/publish` as the signed-in user. Any other field, a
 * missing or mistyped one, or an oversized value is a 400 naming it, without calling REST.
 * Permissions (`pacts:create`), tenant scoping and the publish rules (409 for changed content) are
 * REST's.
 */

import { NextRequest } from 'next/server';
import { PUBLISH_PROXY_PATH, pickPublishBody } from '@lib/pact-publish';
import { forwardPactWrite, pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function POST(request: NextRequest) {
  const picked = pickPublishBody(await request.json().catch(() => null));
  if (!picked.ok) return pactError(400, picked.error);
  return forwardPactWrite(PUBLISH_PROXY_PATH, 'POST', picked.body);
}
