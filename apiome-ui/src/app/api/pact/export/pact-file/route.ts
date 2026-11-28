/**
 * **A pact file** on the Export page — PFX-8.18 (#7315).
 *
 * `GET ?provider=&consumer=[&branch=|&tag=|&version=|&sha=]` reads one stored pact from the Pact
 * Broker API (`…/pacts/provider/{p}/consumer/{c}/latest`, `…/branch/{b}/latest`,
 * `…/latest/{tag}`, `…/version/{v}` or `…/pact-version/{sha}`) and answers `{ pact, fileName }` —
 * the document exactly as published, the broker's `_links` and `createdAt` taken off. Any other,
 * repeated or malformed parameter, or two choices, is a 400 naming it, without calling REST. A pair
 * without such a pact is REST's 404. Permissions (`pacts:view`) and tenant scoping are REST's.
 */

import { NextRequest } from 'next/server';
import { pickPactFileQuery } from '@lib/pact-export';
import { forwardPactFile } from '@lib/pact-export-proxy';
import { pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  const picked = pickPactFileQuery(request.nextUrl.searchParams, false);
  if (!picked.ok) return pactError(400, picked.error);
  return forwardPactFile(picked);
}
