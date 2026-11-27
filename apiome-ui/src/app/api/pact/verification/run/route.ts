/**
 * Run a hosted verification — PFX-8.8 (#7305), the screen for `apiome pact verify`.
 *
 * `POST` takes `{ provider, body }` from **Run a verification** — `body` is the REST body of
 * `POST /v1/tenants/{slug}/pact-verifier/pacts/provider/{p}/verify`, field for field — and
 * forwards it as the signed-in user. REST answers 200 for any run that happened (`outcome` says
 * how: `passed`, `failed`, `incomplete`, `could-not-connect`, `already-verified`, `no-pacts`) and
 * refuses a run that cannot start with its reason — `pact-verify-mutating-production` for requests
 * that change data against a production target. Unknown, mistyped or oversized fields are a 400
 * naming them, without calling REST. Tenancy, `pacts:create` and `verification_evidence:create`
 * are REST's.
 */

import { NextRequest } from 'next/server';
import { pickVerifyRequest, verifyRestPath } from '@lib/pact-verify-run-proxy';
import { forwardPactRun, pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function POST(request: NextRequest) {
  const picked = pickVerifyRequest(await request.json().catch(() => null), 'run');
  if (!picked.ok) return pactError(400, picked.error);
  return forwardPactRun(verifyRestPath(picked.request.provider, 'run'), picked.request.body);
}
