/**
 * Resume a migration run — PFX-8.16 (#7313), the **Copy** step's **Resume** and **Retry the N that
 * failed**.
 *
 * `POST` proxies `POST /v1/tenants/{slug}/pact-migration/runs/{id}/resume`. The body is the source's
 * credentials again, checked by `checkCredentialsBody` (`token`, or `username` / `password`; anything
 * else is a 400 naming it) — they were never stored, so a resume is given them anew. The run reads
 * the source again and skips what it already copied. A malformed run id is a 404 without calling
 * REST; `pacts:create`, `pacts:edit` and tenant scoping are REST's.
 */

import { NextRequest } from 'next/server';
import { MIGRATION_PROXY_PATH, checkCredentialsBody, isRunId } from '@lib/pact-migration';
import { forwardPactWrite, pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function POST(request: NextRequest, context: { params: Promise<{ runId: string }> }) {
  const { runId } = await context.params;
  if (!isRunId(runId)) return pactError(404, 'Unknown migration.');
  const checked = checkCredentialsBody(await request.json().catch(() => null));
  if (!checked.ok) return pactError(400, checked.error);
  return forwardPactWrite(`${MIGRATION_PROXY_PATH}/runs/${runId}/resume`, 'POST', checked.body);
}
