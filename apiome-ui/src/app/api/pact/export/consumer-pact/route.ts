/**
 * **A pact from a project** on the Export page — PFX-8.18 (#7315).
 *
 * `GET ?project=&consumer=[&revision=][&provider=]` forwards
 * `GET /v1/tenants/{slug}/projects/{project}/consumers/{consumer}/pact` — what
 * `apiome pact export-consumer-contract` calls: the consumer's declared surface as a Pact v4 file,
 * its findings and the operation map. Any other, repeated, missing or malformed parameter is a
 * 400 naming it, without calling REST. A refusal keeps REST's `code` and `findings` (a revision that
 * yields no interaction). Permissions (`consumer_contracts:view` and `pacts:view`) and tenant
 * scoping are REST's.
 */

import { NextRequest } from 'next/server';
import { pickConsumerPactQuery } from '@lib/pact-export';
import { forwardExport } from '@lib/pact-export-proxy';
import { pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  const picked = pickConsumerPactQuery(request.nextUrl.searchParams);
  if (!picked.ok) return pactError(400, picked.error);
  return forwardExport(picked.path, 'GET');
}
