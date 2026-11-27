/**
 * **Derive from a project** on the Publish page — PFX-8.3 (#7300).
 *
 * `POST` takes `{ project, consumer, version, branch?, tags?, buildUrl?, revision?, provider? }` and
 * forwards it as `POST /v1/tenants/{slug}/projects/{project}/consumers/{consumer}/pact/publish` —
 * what `apiome pact publish-consumer-contract` calls: REST generates the consumer's Pact v4 document
 * from its declared surface and publishes it for the version. Any other field, a missing, mistyped
 * or oversized one is a 400 naming it, without calling REST. Permissions (`consumer_contracts:view`
 * and `pacts:create`), tenant scoping and the publish rules (409 for changed content) are REST's.
 */

import { NextRequest } from 'next/server';
import { pickDeriveBody } from '@lib/pact-publish-page';
import { forwardPactWrite, pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function POST(request: NextRequest) {
  const picked = pickDeriveBody(await request.json().catch(() => null));
  if (!picked.ok) return pactError(400, picked.error);
  return forwardPactWrite(picked.path, 'POST', picked.body);
}
