/**
 * Read one migration run — PFX-8.16 (#7313): what the wizard's **Copy** step polls.
 *
 * Proxies `GET /v1/tenants/{slug}/pact-migration/runs/{id}?after=` as the signed-in user. Only `after`
 * (a whole number: the last log line the reader has) is accepted; anything else is a 400 naming it,
 * and a malformed run id is a 404 without calling REST. A run of another workspace is REST's 404;
 * `pacts:view` is REST's.
 */

import { NextRequest } from 'next/server';
import { MIGRATION_PROXY_PATH, isRunId, readCursor } from '@lib/pact-migration';
import { forwardPactRead, pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest, context: { params: Promise<{ runId: string }> }) {
  const { runId } = await context.params;
  if (!isRunId(runId)) return pactError(404, 'Unknown migration.');
  const picked = readCursor(request.nextUrl.searchParams);
  if (!picked.ok) return pactError(400, picked.error);
  return forwardPactRead(`${MIGRATION_PROXY_PATH}/runs/${runId}?after=${picked.after}`);
}
