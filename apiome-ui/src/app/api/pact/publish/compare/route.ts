/**
 * **Check it before it counts** on the Publish page — PFX-8.4 (#7301).
 *
 * `POST { pact, against }` forwards one unpublished pact and its provider-version selectors to
 * `POST /v1/tenants/{slug}/pact-broker/pacts/check` as the signed-in user. REST compares the pact with
 * every version the selectors name and **stores nothing**. Any other field, a missing pact, no or too
 * many selectors, or an oversized pact is a 400 naming it, without calling REST. Permissions
 * (`pacts:view`, and `versions:view` for a draft), tenant scoping and the check budget are REST's.
 */

import { NextRequest } from 'next/server';
import { CHECK_PROXY_PATH, pickCompareBody } from '@lib/pact-publish-check';
import { forwardPactRun, pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function POST(request: NextRequest) {
  const picked = pickCompareBody(await request.json().catch(() => null));
  if (!picked.ok) return pactError(400, picked.error);
  return forwardPactRun(CHECK_PROXY_PATH, picked.body);
}
