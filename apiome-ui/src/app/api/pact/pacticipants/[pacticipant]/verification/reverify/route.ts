/**
 * Re-run one pact's verification — PFX-5.5 (#6949).
 *
 * Proxies `POST /v1/tenants/{slug}/pact-verifier/pacts/provider/{p}/consumer/{c}/pact-version/{sha}/reverify`.
 * The query names the pact: `consumer` (a handle) and `sha` (64 hex characters), both required,
 * nothing else. The body is checked by `pickRunBody` (`target_ref` required; `provider_version`,
 * `provider_branch`, `build_url`, `verification` optional; any other field is a 400 naming it). A
 * malformed provider handle is a 404 without calling REST. Permissions (`pacts:create` and
 * `verification_evidence:create`), tenant scoping and the per-pair guard (409) are REST's.
 */

import { NextRequest } from 'next/server';
import { isPacticipantHandle } from '@lib/pact-pacticipants';
import { isPactSha, pickRunBody, reverifyProxyPath } from '@lib/pact-verification';
import { forwardPactRun, pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

/** The query parameters a re-run takes. */
const PARAMETERS = ['consumer', 'sha'];

export async function POST(
  request: NextRequest,
  context: { params: Promise<{ pacticipant: string }> },
) {
  const { pacticipant } = await context.params;
  if (!isPacticipantHandle(pacticipant)) return pactError(404, 'Unknown pacticipant.');
  const search = request.nextUrl.searchParams;
  for (const key of new Set(search.keys())) {
    if (!PARAMETERS.includes(key)) {
      return pactError(400, `Unsupported parameter ${key}: a re-run accepts consumer, sha.`);
    }
    if (search.getAll(key).length > 1) return pactError(400, `The ${key} parameter is given more than once.`);
  }
  const consumer = (search.get('consumer') ?? '').trim();
  const sha = (search.get('sha') ?? '').trim();
  if (!isPacticipantHandle(consumer)) return pactError(400, 'The consumer parameter is not a pacticipant handle.');
  if (!isPactSha(sha)) return pactError(400, 'The sha parameter is not a pact version (64 hex characters).');
  const picked = pickRunBody(await request.json().catch(() => null), false);
  if (!picked.ok) return pactError(400, picked.error);
  return forwardPactRun(reverifyProxyPath(pacticipant, consumer, sha), picked.body);
}
