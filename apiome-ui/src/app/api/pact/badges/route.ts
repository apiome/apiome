/**
 * A pact badge, for the Badges panel's preview — PFX-8.11 (#7308).
 *
 * `GET /api/pact/badges?project=<slug>&pacticipant=<handle>` (or `&provider=…&consumer=…` for one
 * pact) reads REST's public `…/pact-badges/…/badge.svg` and `shields.json` anonymously, in the
 * signed-in user's workspace, and answers `{ tenant, status, svg }`. Any other parameter, a
 * repeated or malformed one, is a 400 naming it, without calling apiome-rest. REST's uniform 404
 * (a private project, nothing bound to it) stays a 404.
 */

import { NextRequest } from 'next/server';
import { parseBadgeQuery } from '@lib/pact-badges';
import { forwardPactBadge } from '@lib/pact-badges-proxy';
import { pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  const parsed = parseBadgeQuery(request.nextUrl.searchParams);
  if (!parsed.ok) return pactError(400, parsed.error);
  return forwardPactBadge(parsed.project, parsed.target);
}
