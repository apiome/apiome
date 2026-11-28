/**
 * Keep a migration in sync — PFX-8.17 (#7314), the **Switch over** step's **Keep copying until
 * everyone has moved**.
 *
 * `GET` proxies `GET /v1/tenants/{slug}/pact-migration/runs/{id}/sync`: whether the copy is kept in
 * sync, when it last copied, since when the old broker has not answered, why it stopped itself.
 *
 * `PUT` proxies `PUT …/runs/{id}/sync`. The body is checked by `checkSyncBody` — `enabled`, an
 * optional `interval_minutes`, and (to switch on) the source's credentials; anything else is a 400
 * naming it. Switching on is the one time the credentials are kept: REST tries them, then seals them
 * until keep-in-sync is switched off. A malformed run id is a 404 without calling REST;
 * `pacts:create`, `pacts:edit` and tenant scoping are REST's.
 */

import { NextRequest } from 'next/server';
import { MIGRATION_PROXY_PATH, checkSyncBody, isRunId } from '@lib/pact-migration';
import { forwardPactRead, forwardPactWrite, pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function GET(_request: NextRequest, context: { params: Promise<{ runId: string }> }) {
  const { runId } = await context.params;
  if (!isRunId(runId)) return pactError(404, 'Unknown migration.');
  return forwardPactRead(`${MIGRATION_PROXY_PATH}/runs/${runId}/sync`);
}

export async function PUT(request: NextRequest, context: { params: Promise<{ runId: string }> }) {
  const { runId } = await context.params;
  if (!isRunId(runId)) return pactError(404, 'Unknown migration.');
  const checked = checkSyncBody(await request.json().catch(() => null));
  if (!checked.ok) return pactError(400, checked.error);
  return forwardPactWrite(`${MIGRATION_PROXY_PATH}/runs/${runId}/sync`, 'PUT', checked.body);
}
