/**
 * Re-run one interaction of a live verification — PFX-8.9 (#7306), the drawer's **Re-run this
 * interaction**.
 *
 * `POST` takes `{ pact_version_sha, case_id }` and nothing else (anything else is a 400 naming it)
 * and forwards it to `POST /v1/tenants/{slug}/pact-verifier/runs/{id}/rerun` as the signed-in user.
 * REST replays the interaction against the run's target with the run's options and publishes
 * nothing; while the run is going it answers 409. Tenancy and permissions are REST's.
 */

import { NextRequest } from 'next/server';
import { isRunId, pickRerunBody, runRestPath } from '@lib/pact-verify-live';
import { forwardPactWrite, pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function POST(request: NextRequest, context: { params: Promise<{ runId: string }> }) {
  const { runId } = await context.params;
  if (!isRunId(runId)) return pactError(404, 'Unknown verification run.');
  const picked = pickRerunBody(await request.json().catch(() => null));
  if (!picked.ok) return pactError(400, picked.error);
  return forwardPactWrite(runRestPath(runId, 'rerun'), 'POST', picked.body);
}
