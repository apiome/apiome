/**
 * Check a provider contract before publishing it — PFX-8.6 (#7303).
 *
 * `POST` takes `{ provider, providerVersion, body }` — the publish body, or `body.contentUrl` for a
 * URL REST reads once — and forwards it as
 * `POST /v1/tenants/{slug}/pact-broker/contracts/provider/{p}/version/{v}/check` as the signed-in
 * user. REST stores nothing and answers with the verdict per consumer pact, the operations no pact
 * uses, the evidence as read and any conflicting contract. Unknown, mistyped or oversized fields
 * are a 400 naming them, without calling REST. Tenancy and `pacts:view` are REST's.
 */

import { NextRequest } from 'next/server';
import { checkContract, pickContractRequest } from '@lib/pact-provider-contract-proxy';
import { answerWithRestCall, pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function POST(request: NextRequest) {
  const picked = pickContractRequest(await request.json().catch(() => null), 'check');
  if (!picked.ok) return pactError(400, picked.error);
  return answerWithRestCall((call) => checkContract(call, picked.request));
}
