/**
 * **Provider test scaffolding** on the Export page — PFX-8.19 (#7316).
 *
 * `GET ?provider=&language=` forwards `GET /v1/tenants/{slug}/pact-provider-tests/{provider}?language=…`
 * — what `apiome pact scaffold-provider-tests` calls: a provider verification test (pact-js,
 * pact-jvm, pact-go or pact-python) with a stub per provider state, and the states not registered in
 * Apiome flagged. Any other, repeated, missing or malformed parameter, or an unknown language, is a
 * 400 naming it, without calling REST. A refusal keeps REST's `code`. Permissions (`pacts:view`) and
 * tenant scoping are REST's.
 */

import { NextRequest } from 'next/server';
import { pickScaffoldQuery } from '@lib/pact-export';
import { forwardExport } from '@lib/pact-export-proxy';
import { pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  const picked = pickScaffoldQuery(request.nextUrl.searchParams);
  if (!picked.ok) return pactError(400, picked.error);
  return forwardExport(picked.path, 'GET');
}
