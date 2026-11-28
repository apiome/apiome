/**
 * The Contracts clean-up rules — PFX-8.14 (#7311), **Settings → Clean-up** (`apiome pact retention
 * show|set`).
 *
 * `GET` proxies `GET /v1/tenants/{slug}/pact-retention/policy` (no parameters: any is a 400 naming
 * it). `PUT` proxies the save; the body is checked by `checkRulesBody` — an unknown field is a 400
 * naming it, and `keep_deployed_or_released: false` is refused ("Deployed and released versions are
 * always kept.") without calling REST. Permissions (`pacts:view` to read, `pacts:delete` to save),
 * tenant scoping and the bounds are REST's.
 */

import { NextRequest } from 'next/server';
import { POLICY_PROXY_PATH, checkRulesBody } from '@lib/pact-retention';
import { forwardPactRead, forwardPactWrite, pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  const [first] = [...request.nextUrl.searchParams.keys()];
  if (first !== undefined) return pactError(400, `Unsupported parameter ${first}: the rules take none.`);
  return forwardPactRead(POLICY_PROXY_PATH);
}

export async function PUT(request: NextRequest) {
  const checked = checkRulesBody(await request.json().catch(() => null));
  if (!checked.ok) return pactError(400, checked.error);
  return forwardPactWrite(POLICY_PROXY_PATH, 'PUT', checked.body);
}
