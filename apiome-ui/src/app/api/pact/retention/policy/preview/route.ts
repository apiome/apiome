/**
 * Preview the Contracts clean-up rules — PFX-8.14 (#7311), **Settings → Clean-up → If it ran now**
 * (`apiome pact retention preview`).
 *
 * `POST` takes `{}` (the saved rules) or `{ rules }` (a draft the tab has not saved), checked by
 * `checkPreviewBody`; anything else is a 400 naming it. Proxies `POST
 * /v1/tenants/{slug}/pact-retention/policy/preview`, which changes nothing. Permissions
 * (`pacts:view`) and tenant scoping are REST's.
 */

import { NextRequest } from 'next/server';
import { PREVIEW_PROXY_PATH, checkPreviewBody } from '@lib/pact-retention';
import { forwardPactWrite, pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function POST(request: NextRequest) {
  const checked = checkPreviewBody(await request.json().catch(() => null));
  if (!checked.ok) return pactError(400, checked.error);
  return forwardPactWrite(PREVIEW_PROXY_PATH, 'POST', checked.body);
}
