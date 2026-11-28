/**
 * Workspace secrets — PFX-8.15 (#7312), **Contracts → Settings → Secrets**.
 *
 * `GET` proxies `GET /v1/tenants/{slug}/pact-secrets` (no parameters: any is a 400 naming it): every
 * secret with what uses it, whether it has a value, and never a value. `POST` creates one; the body is
 * checked by `checkSecretCreate` (`name`, `value`, optional `description`; anything else is a 400
 * naming it). Permissions (`pacts:view` / `pacts:create`), tenant scoping and the limits are REST's.
 */

import { NextRequest } from 'next/server';
import { SECRETS_PROXY_PATH, checkSecretCreate } from '@lib/pact-contract-settings';
import { forwardPactRead, forwardPactWrite, pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  const [first] = [...request.nextUrl.searchParams.keys()];
  if (first !== undefined) return pactError(400, `Unsupported parameter ${first}: the secrets list takes none.`);
  return forwardPactRead(SECRETS_PROXY_PATH);
}

export async function POST(request: NextRequest) {
  const checked = checkSecretCreate(await request.json().catch(() => null));
  if (!checked.ok) return pactError(400, checked.error);
  return forwardPactWrite(SECRETS_PROXY_PATH, 'POST', checked.body);
}
