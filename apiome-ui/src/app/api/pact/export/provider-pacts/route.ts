/**
 * **Every pact for this provider (.zip)** on the Export page — PFX-8.18 (#7315).
 *
 * `GET ?provider=[&branch=|&tag=]` lists the provider's consumers from the Pact Broker API
 * (`…/pacts/provider/{p}/latest[/{tag}]`), reads each consumer's pact (its latest, or its latest on
 * the branch / with the tag) and answers a zip: one file per consumer, exactly as published, and a
 * `README.txt` naming every consumer left out and why. Any other, repeated or malformed parameter,
 * a version or SHA, or two choices, is a 400 naming it, without calling REST. A provider no
 * consumer has such a pact for is a 404. Permissions (`pacts:view`) and tenant scoping are REST's.
 */

import { NextRequest } from 'next/server';
import { pickPactFileQuery } from '@lib/pact-export';
import { forwardProviderPacts } from '@lib/pact-export-proxy';
import { pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  const picked = pickPactFileQuery(request.nextUrl.searchParams, true);
  if (!picked.ok) return pactError(400, picked.error);
  return forwardProviderPacts(picked);
}
