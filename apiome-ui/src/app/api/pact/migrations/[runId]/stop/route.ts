/**
 * Stop a migration run — PFX-8.16 (#7313), the **Copy** step's **Stop**.
 *
 * `POST` proxies `POST /v1/tenants/{slug}/pact-migration/runs/{id}/stop` with no body. The run stops
 * before its next batch; what it copied stays, and resuming carries on where it stopped. A malformed
 * run id is a 404 without calling REST; `pacts:edit` and tenant scoping are REST's.
 */

import { MIGRATION_PROXY_PATH, isRunId } from '@lib/pact-migration';
import { forwardPactWrite, pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function POST(_request: Request, context: { params: Promise<{ runId: string }> }) {
  const { runId } = await context.params;
  if (!isRunId(runId)) return pactError(404, 'Unknown migration.');
  return forwardPactWrite(`${MIGRATION_PROXY_PATH}/runs/${runId}/stop`, 'POST');
}
