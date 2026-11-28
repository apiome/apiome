/**
 * The Contracts commit-status and agent switches — PFX-8.15 (#7312), **Settings → CI and commit
 * statuses** and **Agents**.
 *
 * Proxies `GET /v1/tenants/{slug}/pact-contract-settings` (no parameters: any is a 400 naming it).
 * Permissions (`pacts:view`; `can_edit` is `pacts:delete`) and tenant scoping are REST's.
 */

import { NextRequest } from 'next/server';
import { SETTINGS_PROXY_PATH } from '@lib/pact-contract-settings';
import { forwardPactRead, pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  const [first] = [...request.nextUrl.searchParams.keys()];
  if (first !== undefined) return pactError(400, `Unsupported parameter ${first}: the settings take none.`);
  return forwardPactRead(SETTINGS_PROXY_PATH);
}
