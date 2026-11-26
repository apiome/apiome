/**
 * The workspace's Pact verification overrides — PFX-6.2 (#6954).
 *
 * `GET` proxies `GET /v1/tenants/{slug}/pact-verification-settings/overrides` (no parameters: any
 * is a 400 naming it). `PUT` proxies the save of one provider-wide or per-pair override, with the
 * body checked by `pickOverrideBody` (an unknown field, a malformed handle, or an override that
 * sets nothing is a 400). Permissions (`pacts:view` / `pacts:edit`) and tenant scoping are REST's.
 */

import { NextRequest } from 'next/server';
import { pickPactQuery } from '@lib/pact-detail';
import { OVERRIDES_PROXY_PATH, pickOverrideBody } from '@lib/pact-remediation';
import { forwardPactRead, forwardPactWrite, pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  const picked = pickPactQuery(request.nextUrl.searchParams, false);
  if (!picked.ok) return pactError(400, picked.error);
  return forwardPactRead(OVERRIDES_PROXY_PATH);
}

export async function PUT(request: NextRequest) {
  const picked = pickOverrideBody(await request.json().catch(() => null));
  if (!picked.ok) return pactError(400, picked.error);
  return forwardPactWrite(OVERRIDES_PROXY_PATH, 'PUT', picked.body);
}
