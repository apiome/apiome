/**
 * Preview a hosted verification — PFX-8.8 (#7305).
 *
 * `POST` takes `{ provider, body }` from **Run a verification** — `body` is the run's REST body,
 * target and provider version optional — and forwards it as
 * `POST /v1/tenants/{slug}/pact-verifier/pacts/provider/{p}/verify/preview` as the signed-in user.
 * REST sends nothing to any target and stores nothing; it answers with each rule's pact count, the
 * pacts the run would verify or skip, provider-state coverage and every reason the run would refuse.
 * Unknown, mistyped or oversized fields are a 400 naming them, without calling REST. Tenancy and
 * `pacts:view` are REST's.
 */

import { NextRequest } from 'next/server';
import { pickVerifyRequest, verifyRestPath } from '@lib/pact-verify-run-proxy';
import { forwardPactRun, pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function POST(request: NextRequest) {
  const picked = pickVerifyRequest(await request.json().catch(() => null), 'preview');
  if (!picked.ok) return pactError(400, picked.error);
  return forwardPactRun(verifyRestPath(picked.request.provider, 'preview'), picked.request.body);
}
