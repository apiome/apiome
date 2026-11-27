/**
 * Start a live hosted verification — PFX-8.9 (#7306), the drawer of **Run a verification**.
 *
 * `POST` takes `{ provider, body }` exactly as `/api/pact/verification/run` does (the same strict
 * picker: unknown, mistyped or oversized fields are a 400 naming them, without calling REST) and
 * forwards it to `POST /v1/tenants/{slug}/pact-verifier/pacts/provider/{p}/verify/runs` as the
 * signed-in user. REST checks the run as `…/verify` does — a production target with mutating
 * requests is refused before anything is sent — and answers at once with the run as it starts.
 * Tenancy, `pacts:create` and `verification_evidence:create` are REST's.
 */

import { NextRequest } from 'next/server';
import { pickVerifyRequest, verifyRestPath } from '@lib/pact-verify-run-proxy';
import { forwardPactRun, pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function POST(request: NextRequest) {
  const picked = pickVerifyRequest(await request.json().catch(() => null), 'run');
  if (!picked.ok) return pactError(400, picked.error);
  return forwardPactRun(
    `${verifyRestPath(picked.request.provider, 'run')}/runs`,
    picked.request.body,
  );
}
