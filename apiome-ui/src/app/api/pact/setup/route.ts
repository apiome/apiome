/**
 * The Contracts guided set-up — PFX-8.20 (#7317), `/ade/dashboard/pacts/setup`.
 *
 * - `GET` forwards `GET /v1/tenants/{slug}/pact-setup`: the six sections with their state, the proposed
 *   pacticipants and the GitHub repositories (no parameters: any is a 400 naming it).
 * - `PUT { mark?, first_pact_path?, ci_key?, forget_ci_key? }` saves progress (`checkSaveBody`: an
 *   unknown field or section is a 400 naming it) through `PUT /v1/tenants/{slug}/pact-setup`.
 *
 * Permissions (`pacts:view`; saving is `pacts:delete`) and tenant scoping are REST's.
 */

import { NextRequest } from 'next/server';
import { SETUP_PROXY_PATH, checkSaveBody } from '@lib/pact-setup';
import { forwardPactRead, forwardPactWrite, pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  const [first] = [...request.nextUrl.searchParams.keys()];
  if (first !== undefined) return pactError(400, `Unsupported parameter ${first}: the set-up takes none.`);
  return forwardPactRead(SETUP_PROXY_PATH);
}

export async function PUT(request: NextRequest) {
  const checked = checkSaveBody(await request.json().catch(() => null));
  if (!checked.ok) return pactError(400, checked.error);
  return forwardPactWrite(SETUP_PROXY_PATH, 'PUT', checked.body);
}
