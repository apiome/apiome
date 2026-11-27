/**
 * Read a live hosted verification — PFX-8.9 (#7306): what the run drawer polls.
 *
 * Proxies `GET /v1/tenants/{slug}/pact-verifier/runs/{id}?log_after=` as the signed-in user. Only
 * `log_after` (a whole number) is accepted; anything else is a 400 naming it, and a malformed run id
 * is a 404 without calling REST. A run of another workspace is REST's 404; `pacts:view` is REST's.
 */

import { NextRequest } from 'next/server';
import { isRunId, pickLogAfter, runRestPath } from '@lib/pact-verify-live';
import { forwardPactRead, pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest, context: { params: Promise<{ runId: string }> }) {
  const { runId } = await context.params;
  if (!isRunId(runId)) return pactError(404, 'Unknown verification run.');
  const picked = pickLogAfter(request.nextUrl.searchParams);
  if (!picked.ok) return pactError(400, picked.error);
  return forwardPactRead(`${runRestPath(runId)}?log_after=${picked.logAfter}`);
}
