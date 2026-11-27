/**
 * Stop a live hosted verification — PFX-8.9 (#7306), the drawer's **Stop run**.
 *
 * Forwards `POST /v1/tenants/{slug}/pact-verifier/runs/{id}/stop` as the signed-in user, with no
 * body (a body is a 400). The run ends before its next interaction. A malformed run id is a 404
 * without calling REST; tenancy and `pacts:create` are REST's.
 */

import { NextRequest } from 'next/server';
import { isRunId, runRestPath } from '@lib/pact-verify-live';
import { forwardPactWrite, pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function POST(request: NextRequest, context: { params: Promise<{ runId: string }> }) {
  const { runId } = await context.params;
  if (!isRunId(runId)) return pactError(404, 'Unknown verification run.');
  if ((await request.text()).trim()) return pactError(400, 'Stopping a run takes no body.');
  return forwardPactWrite(runRestPath(runId, 'stop'), 'POST');
}
