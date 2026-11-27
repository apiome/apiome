/**
 * Publish a provider contract — PFX-8.6 (#7303).
 *
 * `POST` takes `{ provider, providerVersion, body, run? }` from the **Publish a provider contract**
 * page: `body` is the REST body of `PUT /v1/tenants/{slug}/pact-broker/contracts/provider/{p}/version/{v}`
 * (the contract inline or as `apiomeVersion`, branch, tags, build URL, `verificationResults`). With
 * `run` (**Run it now**) the hosted provider verifier runs first and a run that does not pass
 * publishes nothing (`{ published: false, run }` with the failing operations); one that passes is
 * cited by its report id. Any other field, a mistyped or oversized one, is a 400 naming it without
 * calling REST. Everything runs as the signed-in user: tenancy, `pacts:create` and the permissions
 * the run and a cited report need are REST's.
 */

import { NextRequest } from 'next/server';
import { pickContractRequest, publishWithEvidence } from '@lib/pact-provider-contract-proxy';
import { answerWithRestCall, pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function POST(request: NextRequest) {
  const picked = pickContractRequest(await request.json().catch(() => null), 'publish');
  if (!picked.ok) return pactError(400, picked.error);
  return answerWithRestCall((call) => publishWithEvidence(call, picked.request));
}
