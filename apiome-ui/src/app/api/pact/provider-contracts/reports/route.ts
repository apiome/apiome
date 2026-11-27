/**
 * The contract-test runs **Reuse an Apiome contract-test run** offers — PFX-8.6 (#7303).
 *
 * `GET ?project=<handle>&version=<label>` forwards
 * `GET /v1/tenants/{slug}/provider-verifications?version_ref=project/<project>/<version>&limit=20`
 * as the signed-in user: the newest provider-verification reports of that version (summaries, no
 * per-operation detail). Without both parameters, or with any other, it is a 400 naming it. Tenancy
 * and `verification_evidence:view` are REST's.
 */

import { NextRequest } from 'next/server';
import { forwardPactRead, pactError } from '@lib/pact-proxy';
import { reportsQuery } from '@lib/pact-provider-contract-proxy';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  const picked = reportsQuery(request.nextUrl.searchParams);
  if (!picked.ok) return pactError(400, picked.error);
  return forwardPactRead(picked.path);
}
