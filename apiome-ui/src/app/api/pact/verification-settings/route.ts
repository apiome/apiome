/**
 * The workspace's Pact verification settings — PFX-6.2 (#6954).
 *
 * `GET` proxies `GET /v1/tenants/{slug}/pact-verification-settings` (no parameters: any is a 400
 * naming it). `PUT` proxies the save, with the body checked by `pickSettingsBody` (every field, in
 * range; an unknown field is a 400 naming it). Permissions (`pacts:view` / `pacts:edit`) and tenant
 * scoping are REST's.
 */

import { NextRequest } from 'next/server';
import { pickPactQuery } from '@lib/pact-detail';
import { SETTINGS_PROXY_PATH, pickSettingsBody } from '@lib/pact-remediation';
import { forwardPactRead, forwardPactWrite, pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  const picked = pickPactQuery(request.nextUrl.searchParams, false);
  if (!picked.ok) return pactError(400, picked.error);
  return forwardPactRead(SETTINGS_PROXY_PATH);
}

export async function PUT(request: NextRequest) {
  const picked = pickSettingsBody(await request.json().catch(() => null));
  if (!picked.ok) return pactError(400, picked.error);
  return forwardPactWrite(SETTINGS_PROXY_PATH, 'PUT', picked.body);
}
