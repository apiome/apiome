/**
 * **A Postman collection** on the Export page — PFX-8.18 (#7315).
 *
 * `POST` takes REST's `PactPostmanRequest` fields (`provider`, `consumer`, `consumerVersion`, `tag`,
 * `branch`, `pactVersionSha`, `pact`, `baseUrl`, `tests`, `allConsumers`, `stateSetup`,
 * `stateChangeUrl`) and forwards them as `POST /v1/tenants/{slug}/pact-postman-collections` — what
 * `apiome pact export-postman` calls. Nothing is stored. Any other field, or one of the wrong type
 * or size, is a 400 naming it; the combination rules are REST's (a 422 with the reason). A refusal
 * keeps REST's `code` and `notices`. Permissions (`pacts:view`) and tenant scoping are REST's.
 */

import { NextRequest } from 'next/server';
import { pickPostmanBody } from '@lib/pact-export';
import { forwardExport } from '@lib/pact-export-proxy';
import { pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function POST(request: NextRequest) {
  const picked = pickPostmanBody(await request.json().catch(() => null));
  if (!picked.ok) return pactError(400, picked.error);
  return forwardExport('pact-postman-collections', 'POST', picked.body);
}
