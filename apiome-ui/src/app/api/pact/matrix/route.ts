/**
 * The broker matrix — PFX-5.4 (#6948).
 *
 * Proxies `GET /v1/tenants/{slug}/pact-broker/matrix` for the **Matrix** page. The browser's
 * query is read with `parseMatrixQuery` and re-written from what it read, so only numbered
 * selectors (`q[N][pacticipant]` with `version`, `latest`, `branch`, `tag`, `environment` or
 * `mainBranch`), `latestby` and `limit` reach REST: anything else, a repeated, empty or oversized
 * parameter, or a selector the broker would refuse is a 400 naming it. `Retry-After` comes back
 * as `retryAfterSeconds`. Permissions (`pacts:view`) and tenant scoping are REST's.
 */

import { NextRequest } from 'next/server';
import { MATRIX_PROXY_PATH, matrixQueryParams, parseMatrixQuery } from '@lib/pact-matrix';
import { forwardPactVerdict, pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  const parsed = parseMatrixQuery(request.nextUrl.searchParams);
  if (!parsed.ok) return pactError(400, parsed.error);
  if (parsed.query.selectors.length === 0) {
    return pactError(400, 'Name at least one pacticipant (q[0][pacticipant]).');
  }
  return forwardPactVerdict(`${MATRIX_PROXY_PATH}?${matrixQueryParams(parsed.query).toString()}`);
}
